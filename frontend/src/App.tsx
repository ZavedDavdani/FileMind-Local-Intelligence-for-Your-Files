import { useState, useEffect, useCallback } from "react";
import { HeaderStatus } from "./components/HeaderStatus";
import { FolderManager } from "./components/FolderManager";
import { IndexingControl } from "./components/IndexingControl";
import { FileList } from "./components/FileList";
import { EventAuditLog } from "./components/EventAuditLog";
import { StateIndicator } from "./components/StateIndicator";
import { SearchModal } from "./components/SearchModal";
import { AskModal } from "./components/AskModal";
import { ChunkInspector } from "./components/ChunkInspector";
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

  const notify = useCallback((msg: string) => {
    setNotification(msg);
    setTimeout(() => {
      setNotification((current) => (current === msg ? null : current));
    }, 3000);
  }, []);

  const refreshAll = useCallback(async () => {
    if (status !== "online") return;
    try {
      const [foldersData, statusData, eventsData] = await Promise.all([
        fetchFolders(),
        fetchIndexingStatus(),
        fetchEvents(undefined, 20),
      ]);
      setFolders(Array.isArray(foldersData) ? foldersData : []);
      setIndexingStatus((prev) => {
        // Only trigger FileList refresh if indexing status/counts changed
        if (
          !prev ||
          prev.total_files !== statusData.total_files ||
          prev.indexed !== statusData.indexed ||
          prev.processing !== statusData.processing ||
          prev.failed !== statusData.failed ||
          prev.queued !== statusData.queued
        ) {
          setRefreshTick((t) => t + 1);
        }
        return statusData;
      });
      setEvents(Array.isArray(eventsData) ? eventsData : []);
      setLastSyncTime(new Date().toISOString());
      setErrorBanner(null);
    } catch (err: unknown) {
      console.error("[App] refreshAll error:", err);
      const msg = err instanceof Error ? err.message : "Sync error";
      setErrorBanner(msg);
    }
  }, [status]);

  // Initial load and periodic polling every 2.5 seconds
  useEffect(() => {
    refreshAll();
    const interval = setInterval(refreshAll, 2500);
    return () => clearInterval(interval);
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
  const handleAddFolder = async (
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
  };

  const handleUpdateFolder = async (id: string, updates: Partial<Folder>) => {
    try {
      await updateFolder(id, updates);
      notify("Folder configuration updated");
      setRefreshTick((t) => t + 1);
      refreshAll();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update folder";
      setErrorBanner(msg);
    }
  };

  const handleDeleteFolder = async (id: string) => {
    try {
      await deleteFolder(id);
      notify("Folder removed from tracking");
      setRefreshTick((t) => t + 1);
      refreshAll();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete folder";
      setErrorBanner(msg);
    }
  };

  const handleRescanFolder = async (id: string) => {
    try {
      await controlIndexing("RESCAN", id);
      notify("Rescan initiated for folder");
      setRefreshTick((t) => t + 1);
      refreshAll();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Rescan failed";
      setErrorBanner(msg);
    }
  };

  // Global Indexing Control Actions
  const handleIndexingControl = async (action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN") => {
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
  };

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

        {/* Discovered & Tracked Files Table */}
        <FileList
          statusFilter={statusFilter}
          onStatusFilterChange={(s) => setStatusFilter(s)}
          onNotification={notify}
          refreshTrigger={refreshTick}
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
          fileId={inspectedChunk.fileId}
          filename={inspectedChunk.filename}
          initialChunkId={inspectedChunk.chunkId}
          onClose={() => setInspectedChunk(null)}
        />
      )}
    </div>
  );
}

export default App;
