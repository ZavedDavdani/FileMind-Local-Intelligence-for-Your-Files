import { useState, useEffect, useRef, memo } from "react";
import { FileItem, IndexStatus } from "../types";
import { fetchFiles, executeSafeAction } from "../services/api";
import { ChunkInspector } from "./ChunkInspector";
import {
  FileText,
  FileCode,
  FileSpreadsheet,
  File as FileGeneric,
  ExternalLink,
  FolderOpen,
  Copy,
  Check,
  Search,
  Hash,
  Layers,
} from "lucide-react";

interface FileListProps {
  files?: FileItem[];
  isLoading?: boolean;
  statusFilter: string | null;
  onStatusFilterChange: (status: string | null) => void;
  onNotification: (msg: string) => void;
  refreshTrigger?: number;
  onOpenKnowledge?: (fileId: string, filename: string) => void;
}

const PAGE_SIZE = 50;

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function getFileIcon(ext: string) {
  switch (ext.toLowerCase()) {
    case ".pdf":
    case ".docx":
    case ".txt":
    case ".md":
      return <FileText className="w-4 h-4 text-indigo-400" />;
    case ".py":
    case ".rs":
    case ".ts":
    case ".tsx":
    case ".js":
    case ".jsx":
    case ".json":
    case ".yaml":
    case ".yml":
    case ".toml":
      return <FileCode className="w-4 h-4 text-emerald-400" />;
    case ".csv":
    case ".xlsx":
      return <FileSpreadsheet className="w-4 h-4 text-amber-400" />;
    default:
      return <FileGeneric className="w-4 h-4 text-slate-400" />;
  }
}

function getStatusBadge(status: IndexStatus) {
  switch (status) {
    case "INDEXED":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 rounded-full flex items-center space-x-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span>INDEXED</span>
        </span>
      );
    case "PROCESSING":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-amber-950/80 text-amber-400 border border-amber-800/60 rounded-full flex items-center space-x-1">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-spin" />
          <span>PROCESSING</span>
        </span>
      );
    case "QUEUED":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-blue-950/80 text-blue-400 border border-blue-800/60 rounded-full">
          QUEUED
        </span>
      );
    case "FAILED":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-rose-950/80 text-rose-400 border border-rose-800/60 rounded-full">
          FAILED
        </span>
      );
    case "SKIPPED":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700 rounded-full">
          SKIPPED
        </span>
      );
    case "MISSING":
      return (
        <span className="px-2 py-0.5 text-[10px] font-semibold bg-amber-900/40 text-amber-500 border border-amber-700/60 rounded-full">
          MISSING
        </span>
      );
    default:
      return null;
  }
}

export const FileList = memo(function FileList({
  files: initialFiles,
  isLoading: initialLoading,
  statusFilter,
  onStatusFilterChange,
  onNotification,
  refreshTrigger,
  onOpenKnowledge,
}: FileListProps) {
  const [files, setFiles] = useState<FileItem[]>(initialFiles || []);
  const [total, setTotal] = useState<number>(initialFiles?.length || 0);
  const [isLoading, setIsLoading] = useState<boolean>(initialLoading ?? false);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [inspectingFile, setInspectingFile] = useState<{ id: string; name: string } | null>(null);
  const latestRequestIdRef = useRef(0);
  const loadedCountRef = useRef(files.length);
  const isInitialMountRef = useRef(true);

  // Synchronize loaded count with files array length
  useEffect(() => {
    loadedCountRef.current = files.length;
  }, [files]);

  // Debounce search query changes by 250ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Effect 1: Filter / Search Change
  // When user actively modifies statusFilter or debouncedSearch, reset pagination to page 1
  useEffect(() => {
    const requestId = ++latestRequestIdRef.current;
    setIsLoading(true);

    fetchFiles(undefined, statusFilter || undefined, PAGE_SIZE, 0, debouncedSearch || undefined)
      .then((res) => {
        if (requestId !== latestRequestIdRef.current) return;
        setFiles(res.files || []);
        setTotal(typeof res.total === "number" ? res.total : (res.files || []).length);
      })
      .catch((err) => {
        if (requestId !== latestRequestIdRef.current) return;
        console.error("[FileList] Failed to load files on filter change:", err);
      })
      .finally(() => {
        if (requestId === latestRequestIdRef.current) {
          setIsLoading(false);
        }
      });
  }, [statusFilter, debouncedSearch]);

  // Effect 2: Background Status Refresh / Mutation Sync
  // Preserves current pagination depth (e.g. 50, 100, 150 files) and does NOT set isLoading (no flicker)
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false;
      return;
    }

    const requestId = ++latestRequestIdRef.current;
    const currentDepth = Math.max(PAGE_SIZE, loadedCountRef.current);

    fetchFiles(undefined, statusFilter || undefined, currentDepth, 0, debouncedSearch || undefined)
      .then((res) => {
        if (requestId !== latestRequestIdRef.current) return;
        setFiles(res.files || []);
        if (typeof res.total === "number") {
          setTotal(res.total);
        }
      })
      .catch((err) => {
        if (requestId !== latestRequestIdRef.current) return;
        console.error("[FileList] Background refresh failed:", err);
      });
  }, [refreshTrigger]);

  const handleLoadMore = async () => {
    if (isLoadingMore || files.length >= total) return;
    setIsLoadingMore(true);
    const nextOffset = files.length;
    try {
      const res = await fetchFiles(
        undefined,
        statusFilter || undefined,
        PAGE_SIZE,
        nextOffset,
        debouncedSearch || undefined
      );
      setFiles((prev) => {
        const seenIds = new Set(prev.map((f) => f.file_id || f.path));
        const newItems = (res.files || []).filter((f) => !seenIds.has(f.file_id || f.path));
        return [...prev, ...newItems];
      });
      if (typeof res.total === "number") {
        setTotal(res.total);
      }
    } catch (err: unknown) {
      console.error("[FileList] Failed to load more files:", err);
      const msg = err instanceof Error ? err.message : "Failed to load more files";
      onNotification(`Error: ${msg}`);
    } finally {
      setIsLoadingMore(false);
    }
  };

  const handleAction = async (action: "OPEN_FILE" | "OPEN_FOLDER" | "COPY_PATH", path: string) => {
    try {
      if (action === "COPY_PATH") {
        await navigator.clipboard.writeText(path);
        setCopiedPath(path);
        setTimeout(() => setCopiedPath(null), 2000);
        onNotification("Path copied to clipboard");
        return;
      }

      const res = await executeSafeAction(action, path);
      onNotification(res.message);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Action failed";
      onNotification(`Error: ${msg}`);
    }
  };

  return (
    <div className="flex-1 bg-dark-800/60 border border-dark-700/60 rounded-2xl flex flex-col min-h-0 shadow-lg overflow-hidden">
      {/* Header with Search and Filter */}
      <div className="p-4 border-b border-dark-700/60 flex items-center justify-between space-x-3">
        <div className="flex items-center space-x-2">
          <FileText className="w-5 h-5 text-indigo-400" />
          <h2 className="text-sm font-semibold text-white">Tracked Files</h2>
          <span className="text-xs bg-dark-700 px-2 py-0.5 rounded-full text-slate-300 font-mono">
            {files.length === total ? `${total}` : `${files.length} of ${total}`}
          </span>
        </div>

        {/* Search Bar & Filter */}
        <div className="flex items-center space-x-2 flex-1 max-w-md justify-end">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              aria-label="Search files by filename, path, or SHA"
              placeholder="Search filename, relative path, or SHA-256 across corpus..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-dark-900 border border-dark-600 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
            />
          </div>

          {/* Status Filter Dropdown */}
          <select
            value={statusFilter || ""}
            aria-label="Filter files by index status"
            onChange={(e) => onStatusFilterChange(e.target.value || null)}
            className="bg-dark-900 border border-dark-600 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
          >
            <option value="">All Statuses</option>
            <option value="INDEXED">Indexed</option>
            <option value="QUEUED">Queued</option>
            <option value="PROCESSING">Processing</option>
            <option value="FAILED">Failed</option>
            <option value="SKIPPED">Skipped</option>
            <option value="MISSING">Missing</option>
          </select>
        </div>
      </div>

      {/* Files Table / List */}
      <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-dark-700/40 font-mono text-xs flex flex-col">
        {isLoading && files.length === 0 && (
          <div className="p-8 text-center text-slate-400">Loading tracked files...</div>
        )}

        {!isLoading && files.length === 0 && (
          <div className="p-8 text-center text-slate-500 text-xs">
            No files match the current query or filter.
          </div>
        )}

        <div className="divide-y divide-dark-700/40 flex-1">
          {files.map((file) => (
            <div
              key={file.file_id || file.path}
              className="px-4 py-2.5 flex items-center justify-between hover:bg-dark-700/30 transition-colors group"
            >
              {/* File Info */}
              <div className="flex items-center space-x-3 min-w-0 flex-1 pr-4">
                {getFileIcon(file.extension)}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-slate-100 truncate">{file.filename}</span>
                    {getStatusBadge(file.index_status)}
                  </div>
                  <div className="flex items-center space-x-3 text-[11px] text-slate-400 mt-0.5 truncate">
                    <span className="truncate" title={file.relative_path}>
                      {file.relative_path}
                    </span>
                    {file.sha256 && (
                      <span
                        className="text-[10px] text-slate-500 flex items-center space-x-1 shrink-0"
                        title={`SHA-256: ${file.sha256}`}
                      >
                        <Hash className="w-3 h-3 text-slate-600" />
                        <span>{file.sha256.substring(0, 12)}...</span>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Metadata & Actions */}
              <div className="flex items-center space-x-4 shrink-0 text-slate-400 text-[11px]">
                <span className="w-16 text-right font-mono">{formatBytes(file.size_bytes)}</span>

                {/* Action Buttons */}
                <div className="flex items-center space-x-1 opacity-80 group-hover:opacity-100">
                  {file.file_id && file.index_status === "INDEXED" && (
                    <button onClick={() => onOpenKnowledge?.(file.file_id!, file.filename)} className="p-1 text-indigo-300 hover:bg-dark-600 rounded" title="Open local document insight and related files" aria-label={`Open knowledge details for ${file.filename}`}><span className="text-[10px]">Insight</span></button>
                  )}
                  {file.file_id && file.index_status === "INDEXED" && (
                    <button
                      onClick={() => setInspectingFile({ id: file.file_id!, name: file.filename })}
                      className="p-1 hover:text-cyan-300 hover:bg-dark-600 rounded flex items-center space-x-1 px-1.5 py-0.5 bg-dark-700/60 border border-dark-600 text-cyan-400"
                      title="Inspect extracted chunks and provenance"
                      aria-label={`Inspect chunks for ${file.filename}`}
                    >
                      <Layers className="w-3 h-3" />
                      <span className="text-[10px]">Chunks</span>
                    </button>
                  )}
                  <button
                    onClick={() => handleAction("OPEN_FILE", file.path)}
                    className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                    title="Open file with default app"
                    aria-label={`Open ${file.filename} with default app`}
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleAction("OPEN_FOLDER", file.path)}
                    className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                    title="Show in Explorer"
                    aria-label={`Show ${file.filename} in Explorer`}
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleAction("COPY_PATH", file.path)}
                    className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                    title="Copy full path"
                    aria-label={`Copy full path of ${file.filename}`}
                  >
                    {copiedPath === file.path ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Load More Pagination Footer */}
        {files.length < total && (
          <div className="p-3 text-center bg-dark-900/40 border-t border-dark-700/40">
            <button
              onClick={handleLoadMore}
              disabled={isLoadingMore}
              aria-label="Load more files"
              className="px-4 py-1.5 text-xs font-medium text-indigo-400 hover:text-indigo-200 bg-indigo-950/60 hover:bg-indigo-900/60 border border-indigo-800/60 rounded-lg transition disabled:opacity-50 cursor-pointer"
            >
              {isLoadingMore
                ? "Loading more files..."
                : `Load More (${total - files.length} remaining)`}
            </button>
          </div>
        )}
      </div>

      {/* Chunk Inspector Modal */}
      {inspectingFile && (
        <ChunkInspector
          key={inspectingFile.id}
          fileId={inspectingFile.id}
          filename={inspectingFile.name}
          onClose={() => setInspectingFile(null)}
        />
      )}
    </div>
  );
});

