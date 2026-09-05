import { useState, useEffect, useCallback, useRef } from "react";
import { HeaderStatus } from "./components/HeaderStatus";
import { FolderManager } from "./components/FolderManager";
import { IndexingControl } from "./components/IndexingControl";
import { FileList } from "./components/FileList";
import { EventAuditLog } from "./components/EventAuditLog";
import { StateIndicator } from "./components/StateIndicator";
import { SearchModal } from "./components/SearchModal";
import { AskModal } from "./components/AskModal";
import { ChunkInspector } from "./components/ChunkInspector";
import { SecondBrainSheet } from "./components/SecondBrainSheet";
import { FolderSummaryBanner } from "./components/FolderSummaryBanner";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { KnowledgeWorkspace } from "./components/KnowledgeWorkspace";
import { SettingsModal } from "./components/SettingsModal";
import { OnboardingModal } from "./components/OnboardingModal";
import { useBackendHealth } from "./hooks/useBackendHealth";
import {
  fetchFolders,
  createFolder,
  updateFolder,
  deleteFolder,
  fetchIndexingStatus,
  controlIndexing,
  fetchEvents,
} from "./services/api";
import { Folder, IndexingStatus, EventItem, IntegrityMode } from "./types";
import {
  AlertCircle,
  Search,
  Sparkles,
  LayoutDashboard,
  MessageSquare,
  BookOpen,
  Settings,
  HelpCircle,
} from "lucide-react";

type MainViewTab = "DASHBOARD" | "CHAT" | "KNOWLEDGE";

export function App() {
  const { status, healthData, latencyMs, errorMessage, recheck } = useBackendHealth();

  const [activeView, setActiveView] = useState<MainViewTab>("DASHBOARD");
  const [folders, setFolders] = useState<Folder[]>([]);
  const [indexingStatus, setIndexingStatus] = useState<IndexingStatus | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState<number>(0);
  const [notification, setNotification] = useState<string | null>(null);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Modals
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isAskOpen, setIsAskOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isOnboardingOpen, setIsOnboardingOpen] = useState(false);

  const [inspectedChunk, setInspectedChunk] = useState<{
    fileId: string;
    filename: string;
    chunkId: string;
  } | null>(null);
  const [knowledgeFile, setKnowledgeFile] = useState<{ id: string; name: string } | null>(null);

  const notify = useCallback((msg: string) => {
    setNotification(msg);
    setTimeout(() => {
      setNotification((current) => (current === msg ? null : current));
    }, 3000);
  }, []);

  const isRefreshingRef = useRef(false);
  const prevIndexingStatusRef = useRef<IndexingStatus | null>(null);

  // Check onboarding on mount
  useEffect(() => {
    const onboarded = localStorage.getItem("filemind_onboarding_completed");
    if (!onboarded) {
      setIsOnboardingOpen(true);
    }
  }, []);

  const areFoldersEqual = (prev: Folder[], next: Folder[]): boolean => {
    if (prev === next) return true;
    if (prev.length !== next.length) return false;
    for (let i = 0; i < prev.length; i++) {
      const p = prev[i];
      const n = next[i];
      if (
        p.folder_id !== n.folder_id ||
        p.path !== n.path ||
        p.recursive !== n.recursive ||
        p.integrity_mode !== n.integrity_mode ||
        p.indexing_enabled !== n.indexing_enabled ||
        p.updated_at !== n.updated_at
      ) {
        return false;
      }
    }
    return true;
  };

  const areEventsEqual = (prev: EventItem[], next: EventItem[]): boolean => {
    if (prev === next) return true;
    if (prev.length !== next.length) return false;
    for (let i = 0; i < prev.length; i++) {
      const p = prev[i];
      const n = next[i];
      if (
        p.event_id !== n.event_id ||
        p.processing_status !== n.processing_status ||
        p.observed_at !== n.observed_at ||
        p.path !== n.path ||
        p.event_type !== n.event_type
      ) {
        return false;
      }
    }
    return true;
  };

  const areIndexingStatusesEqual = (
    prev: IndexingStatus | null,
    next: IndexingStatus | null
  ): boolean => {
    if (prev === next) return true;
    if (!prev || !next) return false;
    return (
      prev.total_files === next.total_files &&
      prev.indexed === next.indexed &&
      prev.processing === next.processing &&
      prev.failed === next.failed &&
      prev.queued === next.queued &&
      prev.discovered === next.discovered &&
      prev.missing === next.missing &&
      prev.skipped === next.skipped &&
      prev.is_running === next.is_running &&
      prev.is_paused === next.is_paused &&
      prev.progress_percent === next.progress_percent
    );
  };

  const refreshAll = useCallback(async () => {
    if (status !== "online" || isRefreshingRef.current) return;
    isRefreshingRef.current = true;
    try {
      const [foldersData, statusData, eventsData] = await Promise.all([
        fetchFolders(),
        fetchIndexingStatus(),
        fetchEvents(undefined, 20),
      ]);
      const validFolders = Array.isArray(foldersData) ? foldersData : [];
      setFolders((prev) => (areFoldersEqual(prev, validFolders) ? prev : validFolders));

      const prev = prevIndexingStatusRef.current;
      const hasChanged = !areIndexingStatusesEqual(prev, statusData);

      if (hasChanged) {
        prevIndexingStatusRef.current = statusData;
        setIndexingStatus(statusData);
        setRefreshTick((t) => t + 1);
      }

      const validEvents = Array.isArray(eventsData) ? eventsData : [];
      setEvents((prev) => (areEventsEqual(prev, validEvents) ? prev : validEvents));

      setLastSyncTime(new Date().toISOString());
      setErrorBanner(null);
    } catch (err: unknown) {
      console.error("[App] refreshAll error:", err);
      const msg = err instanceof Error ? err.message : "Sync error";
      setErrorBanner(msg);
    } finally {
      isRefreshingRef.current = false;
    }
  }, [status]);

  // Initial load and periodic polling every 2.5 seconds with exponential backoff
  useEffect(() => {
    let mounted = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    let consecutiveErrors = 0;

    const scheduleNextPoll = (delayMs: number) => {
      if (!mounted) return;
      if (timerId) clearTimeout(timerId);
      timerId = setTimeout(async () => {
        if (!mounted) return;
        if (typeof document !== "undefined" && document.hidden) {
          scheduleNextPoll(5000);
          return;
        }
        try {
          await refreshAll();
          consecutiveErrors = 0;
          const currentStatus = prevIndexingStatusRef.current;
          const isBusy =
            currentStatus && (currentStatus.processing > 0 || currentStatus.queued > 0);
          scheduleNextPoll(isBusy ? 2500 : 5000);
        } catch {
          consecutiveErrors++;
          const backoff = Math.min(2500 * Math.pow(2, consecutiveErrors - 1), 15000);
          scheduleNextPoll(backoff);
        }
      }, delayMs);
    };

    scheduleNextPoll(0);

    const handleVisibility = () => {
      if (mounted && typeof document !== "undefined" && !document.hidden) {
        consecutiveErrors = 0;
        scheduleNextPoll(0);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      mounted = false;
      if (timerId) clearTimeout(timerId);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshAll]);

  // Global Ctrl+K (Search) and Ctrl+J (Ask) shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsSearchOpen((prev) => !prev);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setIsAskOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Folder Operations
  const handleAddFolder = useCallback(
    async (
      path: string,
      recursive: boolean,
      mode: IntegrityMode,
      exclusions: string[]
    ) => {
      try {
        const created = await createFolder(path, recursive, mode, true, exclusions);
        notify(`Registered folder: ${created.path}`);
        setRefreshTick((t) => t + 1);
        refreshAll();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to register folder";
        setErrorBanner(msg);
      }
    },
    [notify, refreshAll]
  );

  const handleUpdateFolder = useCallback(
    async (id: string, updates: Partial<Folder>) => {
      try {
        await updateFolder(id, updates);
        notify("Folder configuration updated");
        setRefreshTick((t) => t + 1);
        refreshAll();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to update folder";
        setErrorBanner(msg);
      }
    },
    [notify, refreshAll]
  );

  const handleDeleteFolder = useCallback(
    async (id: string) => {
      try {
        await deleteFolder(id);
        notify("Folder removed from tracking");
        setRefreshTick((t) => t + 1);
        refreshAll();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to delete folder";
        setErrorBanner(msg);
      }
    },
    [notify, refreshAll]
  );

  const handleRescanFolder = useCallback(
    async (id: string) => {
      try {
        await controlIndexing("RESCAN", id);
        notify("Rescan initiated for folder");
        setRefreshTick((t) => t + 1);
        refreshAll();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Rescan failed";
        setErrorBanner(msg);
      }
    },
    [notify, refreshAll]
  );

  // Global Indexing Control Actions
  const handleIndexingControl = useCallback(
    async (action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN") => {
      try {
        const newStatus = await controlIndexing(action);
        setIndexingStatus(newStatus);
        notify(`Action triggered: ${action}`);
        setRefreshTick((t) => t + 1);
        refreshAll();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Control action failed";
        setErrorBanner(msg);
      }
    },
    [notify, refreshAll]
  );

  const handleStatusFilterChange = useCallback((s: string | null) => {
    setStatusFilter(s);
  }, []);

  const handleOpenKnowledge = useCallback((id: string, name: string) => {
    setKnowledgeFile({ id, name });
  }, []);

  const handleInspectChunk = useCallback((fileId: string, filename: string, chunkId: string) => {
    setInspectedChunk({ fileId, filename, chunkId });
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col bg-dark-900 text-slate-100 overflow-hidden font-sans">
      {/* Top Header with Backend Status & Navigation */}
      <HeaderStatus
        status={status}
        healthData={healthData}
        latencyMs={latencyMs}
        isIndexing={Boolean(
          indexingStatus && !indexingStatus.is_paused && indexingStatus.processing > 0
        )}
        onRetry={recheck}
      />

      {/* Main Workspace Navigation Bar */}
      <div className="bg-dark-850 border-b border-slate-800 px-5 py-2.5 flex items-center justify-between shrink-0">
        {/* Navigation Tabs */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveView("DASHBOARD")}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeView === "DASHBOARD"
                ? "bg-purple-600 text-white shadow"
                : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            <span>Files & Folders</span>
          </button>

          <button
            onClick={() => setActiveView("CHAT")}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeView === "CHAT"
                ? "bg-purple-600 text-white shadow"
                : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Chat Workspace</span>
          </button>

          <button
            onClick={() => setActiveView("KNOWLEDGE")}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeView === "KNOWLEDGE"
                ? "bg-purple-600 text-white shadow"
                : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Knowledge & Synthesis</span>
          </button>
        </div>

        {/* Global Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsAskOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold rounded-lg shadow transition"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Ask</span>
            <kbd className="bg-purple-800/80 px-1 py-0.5 rounded font-mono text-[9px] text-purple-200">
              Ctrl+J
            </kbd>
          </button>

          <button
            onClick={() => setIsSearchOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-750 hover:bg-dark-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
          >
            <Search className="w-3.5 h-3.5 text-slate-400" />
            <span>Search</span>
            <kbd className="bg-dark-850 px-1 py-0.5 rounded font-mono text-[9px] text-slate-400">
              Ctrl+K
            </kbd>
          </button>

          <button
            onClick={() => setIsSettingsOpen(true)}
            className="p-1.5 bg-dark-750 hover:bg-dark-700 text-slate-400 hover:text-slate-200 rounded-lg border border-slate-700 transition"
            title="Settings & Diagnostics"
          >
            <Settings className="w-4 h-4" />
          </button>

          <button
            onClick={() => setIsOnboardingOpen(true)}
            className="p-1.5 bg-dark-750 hover:bg-dark-700 text-slate-400 hover:text-slate-200 rounded-lg border border-slate-700 transition"
            title="Help & Onboarding Guide"
          >
            <HelpCircle className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-h-0 p-4 space-y-4 overflow-hidden">
        {/* Backend Startup Error Banner */}
        {status === "unavailable" && (
          <div className="bg-rose-950/40 border border-rose-500/30 rounded-xl p-4 flex items-start space-x-3 text-rose-200 text-xs shrink-0">
            <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-rose-300">Backend Startup Diagnostic</p>
              <p className="mt-0.5 text-rose-200/90">{errorMessage}</p>
              <p className="mt-2 text-[11px] text-rose-300/70">
                Tauri supervises the local backend at{" "}
                <code className="bg-rose-950/80 px-1 py-0.5 rounded font-mono">
                  127.0.0.1:24823
                </code>
                .
              </p>
            </div>
          </div>
        )}

        {/* Action / Scan Error Banner */}
        {errorBanner && (
          <div className="bg-amber-950/40 border border-amber-500/30 rounded-xl p-3 flex items-center justify-between text-amber-200 text-xs shrink-0">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>{errorBanner}</span>
            </div>
            <button
              onClick={() => setErrorBanner(null)}
              className="text-amber-400 hover:text-white text-xs px-2 py-0.5 bg-amber-900/40 rounded"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* View Routing */}
        {activeView === "DASHBOARD" && (
          <div className="flex-1 overflow-y-auto space-y-4 pr-1">
            {/* Top Grid: Registered Folders & Indexing Controls */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <FolderManager
                folders={folders}
                onAddFolder={handleAddFolder}
                onUpdateFolder={handleUpdateFolder}
                onDeleteFolder={handleDeleteFolder}
                onRescanFolder={handleRescanFolder}
                disabled={status !== "online"}
              />

              <IndexingControl
                status={indexingStatus}
                onControl={handleIndexingControl}
                disabled={status !== "online"}
              />
            </div>
            <FolderSummaryBanner folders={folders} />

            {/* Discovered & Tracked Files Table */}
            <FileList
              statusFilter={statusFilter}
              onStatusFilterChange={handleStatusFilterChange}
              onNotification={notify}
              refreshTrigger={refreshTick}
              onOpenKnowledge={handleOpenKnowledge}
            />

            {/* Filesystem Event Audit Log */}
            <EventAuditLog events={events} />
          </div>
        )}

        {activeView === "CHAT" && (
          <ChatWorkspace
            onInspectChunk={handleInspectChunk}
            onNotify={notify}
          />
        )}

        {activeView === "KNOWLEDGE" && (
          <KnowledgeWorkspace
            onInspectChunk={handleInspectChunk}
            onOpenKnowledge={handleOpenKnowledge}
            onNotify={notify}
          />
        )}
      </main>

      {/* Footer State & Persistence Indicator */}
      <StateIndicator
        lastUpdatedTime={lastSyncTime}
        notification={notification}
        totalFiles={indexingStatus?.total_files || 0}
      />

      {/* Modals & Overlays */}
      <AskModal
        isOpen={isAskOpen}
        onClose={() => setIsAskOpen(false)}
        onInspectChunk={handleInspectChunk}
      />

      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        folders={folders}
        onInspectChunk={handleInspectChunk}
      />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onNotify={notify}
      />

      <OnboardingModal
        isOpen={isOnboardingOpen}
        onClose={() => setIsOnboardingOpen(false)}
      />

      {inspectedChunk && (
        <ChunkInspector
          key={`${inspectedChunk.fileId}-${inspectedChunk.chunkId || "default"}`}
          fileId={inspectedChunk.fileId}
          filename={inspectedChunk.filename}
          initialChunkId={inspectedChunk.chunkId}
          onClose={() => setInspectedChunk(null)}
        />
      )}

      {knowledgeFile && (
        <SecondBrainSheet
          fileId={knowledgeFile.id}
          filename={knowledgeFile.name}
          onClose={() => setKnowledgeFile(null)}
          onInspectChunk={(fileId, filename, chunkId) => {
            setKnowledgeFile(null);
            handleInspectChunk(fileId, filename, chunkId);
          }}
        />
      )}
    </div>
  );
}

export default App;
