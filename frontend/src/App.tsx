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
import { AlertCircle, Search, Sparkles } from "lucide-react";

export function App() {
  const { status, healthData, latencyMs, errorMessage, recheck } = useBackendHealth();

  const [folders, setFolders] = useState<Folder[]>([]);
  const [indexingStatus, setIndexingStatus] = useState<IndexingStatus | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState<number>(0);
  const [notification, setNotification] = useState<string | null>(null);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isAskOpen, setIsAskOpen] = useState(false);
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

  const areIndexingStatusesEqual = (prev: IndexingStatus | null, next: IndexingStatus | null): boolean => {
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

  // Initial load and periodic polling every 2.5 seconds with exponential error backoff
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
          scheduleNextPoll(2500);
          return;
        }
        try {
          await refreshAll();
          consecutiveErrors = 0;
          scheduleNextPoll(2500);
        } catch {
          consecutiveErrors++;
          // Exponential backoff: 2.5s, 5s, 10s, max 15s
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

  return (
    <div className="h-screen w-screen flex flex-col bg-dark-900 text-slate-100 overflow-hidden font-sans">
      {/* Top Header with Backend Status */}
      <HeaderStatus
        status={status}
        healthData={healthData}
        latencyMs={latencyMs}
        isIndexing={Boolean(indexingStatus && !indexingStatus.is_paused && indexingStatus.processing > 0)}
        onRetry={recheck}
      />

      {/* Main Workspace Layout */}
      <main className="flex-1 flex flex-col min-h-0 p-5 space-y-4 overflow-y-auto">
        {/* Search Bar / Quick Action */}
        <div className="flex items-center justify-between bg-dark-800/90 border border-slate-700/60 rounded-xl px-4 py-2.5 shadow-sm">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsAskOpen(true)}
              className="flex items-center gap-2 px-3.5 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold rounded-lg shadow transition"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Ask FileMind</span>
              <kbd className="bg-purple-800/80 px-1.5 py-0.5 rounded font-mono text-[10px] text-purple-200">
                Ctrl + J
              </kbd>
            </button>

            <button
              onClick={() => setIsSearchOpen(true)}
              className="flex items-center gap-2 px-3.5 py-1.5 bg-dark-700 hover:bg-dark-600 text-slate-200 text-xs font-semibold rounded-lg border border-slate-600/70 shadow transition"
            >
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <span>Search Evidence</span>
              <kbd className="bg-dark-800 px-1.5 py-0.5 rounded font-mono text-[10px] text-slate-400">
                Ctrl + K
              </kbd>
            </button>
            <span className="text-xs text-slate-400 hidden sm:inline">
              Deterministic local hybrid retrieval & grounded AI
            </span>
          </div>
          {indexingStatus && (
            <div className="text-xs text-slate-400 font-mono hidden md:block">
              {indexingStatus.indexed} / {indexingStatus.total_files} files indexed
            </div>
          )}
        </div>

        {/* Backend Error Diagnostic Banner */}
        {status === "unavailable" && (
          <div className="bg-rose-950/40 border border-rose-500/30 rounded-xl p-4 flex items-start space-x-3 text-rose-200 text-xs">
            <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-rose-300">Backend Startup Diagnostic</p>
              <p className="mt-0.5 text-rose-200/90">{errorMessage}</p>
              <p className="mt-2 text-[11px] text-rose-300/70">
                Tauri supervises the local backend at{" "}
                <code className="bg-rose-950/80 px-1 py-0.5 rounded font-mono">127.0.0.1:24823</code>.
              </p>
            </div>
          </div>
        )}

        {/* Action / Scan Error Banner */}
        {errorBanner && (
          <div className="bg-amber-950/40 border border-amber-500/30 rounded-xl p-3 flex items-center justify-between text-amber-200 text-xs">
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
      </main>

      {/* Footer State & Persistence Indicator */}
      <StateIndicator
        lastUpdatedTime={lastSyncTime}
        notification={notification}
        totalFiles={indexingStatus?.total_files || 0}
      />

      {/* Phase 5: Grounded Ask FileMind Modal */}
      <AskModal
        isOpen={isAskOpen}
        onClose={() => setIsAskOpen(false)}
        onInspectChunk={(fileId, filename, chunkId) => setInspectedChunk({ fileId, filename, chunkId })}
      />

      {/* Phase 3: Spotlight / Raycast Search Modal */}
      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        folders={folders}
        onInspectChunk={(fileId, filename, chunkId) => setInspectedChunk({ fileId, filename, chunkId })}
      />

      {/* Document Intelligence: Chunk Inspector Modal */}
      {inspectedChunk && (
        <ChunkInspector
          key={`${inspectedChunk.fileId}-${inspectedChunk.chunkId || "default"}`}
          fileId={inspectedChunk.fileId}
          filename={inspectedChunk.filename}
          initialChunkId={inspectedChunk.chunkId}
          onClose={() => setInspectedChunk(null)}
        />
      )}
      {knowledgeFile && <SecondBrainSheet fileId={knowledgeFile.id} filename={knowledgeFile.name} onClose={() => setKnowledgeFile(null)} onInspectChunk={(fileId, filename, chunkId) => { setKnowledgeFile(null); setInspectedChunk({ fileId, filename, chunkId }); }} />}
    </div>
  );
}

export default App;
