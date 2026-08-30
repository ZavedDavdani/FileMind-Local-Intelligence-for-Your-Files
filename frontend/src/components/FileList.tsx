import { useState } from "react";
import { FileItem, IndexStatus } from "../types";
import { executeSafeAction } from "../services/api";
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
  files: FileItem[];
  isLoading?: boolean;
  statusFilter: string | null;
  onStatusFilterChange: (status: string | null) => void;
  onNotification: (msg: string) => void;
}

function getFileIcon(ext: string) {
  const cleanExt = ext.toLowerCase();
  if ([".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".json", ".html", ".css"].includes(cleanExt)) {
    return <FileCode className="w-4 h-4 text-cyan-400 shrink-0" />;
  }
  if ([".csv", ".xlsx", ".xls"].includes(cleanExt)) {
    return <FileSpreadsheet className="w-4 h-4 text-emerald-400 shrink-0" />;
  }
  if ([".pdf", ".txt", ".md", ".docx", ".doc", ".pptx"].includes(cleanExt)) {
    return <FileText className="w-4 h-4 text-indigo-400 shrink-0" />;
  }
  return <FileGeneric className="w-4 h-4 text-slate-400 shrink-0" />;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function getStatusBadge(status: IndexStatus) {
  switch (status) {
    case "INDEXED":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950/60 text-emerald-300 border border-emerald-500/40">
          INDEXED
        </span>
      );
    case "PROCESSING":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-950/60 text-amber-300 border border-amber-500/40 animate-pulse">
          PROCESSING
        </span>
      );
    case "QUEUED":
    case "DISCOVERED":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-indigo-950/60 text-indigo-300 border border-indigo-500/40">
          QUEUED
        </span>
      );
    case "FAILED":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-950/60 text-rose-300 border border-rose-500/40">
          FAILED
        </span>
      );
    case "SKIPPED":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
          SKIPPED
        </span>
      );
    case "MISSING":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-dark-900 text-slate-500 border border-dark-700 line-through">
          MISSING
        </span>
      );
    default:
      return null;
  }
}

export function FileList({
  files,
  isLoading,
  statusFilter,
  onStatusFilterChange,
  onNotification,
}: FileListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [inspectingFile, setInspectingFile] = useState<{ id: string; name: string } | null>(null);

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

  const filteredFiles = files.filter((f) => {
    const matchesSearch =
      f.filename.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.relative_path.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (f.sha256 && f.sha256.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesStatus = !statusFilter || f.index_status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="flex-1 bg-dark-800/60 border border-dark-700/60 rounded-2xl flex flex-col min-h-0 shadow-lg overflow-hidden">
      {/* Header with Search and Filter */}
      <div className="p-4 border-b border-dark-700/60 flex items-center justify-between space-x-3">
        <div className="flex items-center space-x-2">
          <FileText className="w-5 h-5 text-indigo-400" />
          <h2 className="text-sm font-semibold text-white">Tracked Files</h2>
          <span className="text-xs bg-dark-700 px-2 py-0.5 rounded-full text-slate-300 font-mono">
            {filteredFiles.length}
          </span>
        </div>

        {/* Search Bar & Filter */}
        <div className="flex items-center space-x-2 flex-1 max-w-md justify-end">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search filename, relative path, or SHA-256..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-dark-900 border border-dark-600 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
            />
          </div>

          {/* Status Filter Dropdown */}
          <select
            value={statusFilter || ""}
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
      <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-dark-700/40 font-mono text-xs">
        {isLoading && (
          <div className="p-8 text-center text-slate-400">Loading tracked files...</div>
        )}

        {!isLoading && filteredFiles.length === 0 && (
          <div className="p-8 text-center text-slate-500 text-xs">
            No files match the current query or filter.
          </div>
        )}

        {filteredFiles.map((file) => (
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
                  <button
                    onClick={() => setInspectingFile({ id: file.file_id!, name: file.filename })}
                    className="p-1 hover:text-cyan-300 hover:bg-dark-600 rounded flex items-center space-x-1 px-1.5 py-0.5 bg-dark-700/60 border border-dark-600 text-cyan-400"
                    title="Inspect extracted chunks and provenance"
                  >
                    <Layers className="w-3 h-3" />
                    <span className="text-[10px]">Chunks</span>
                  </button>
                )}
                <button
                  onClick={() => handleAction("OPEN_FILE", file.path)}
                  className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                  title="Open file with default app"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleAction("OPEN_FOLDER", file.path)}
                  className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                  title="Show in Explorer"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleAction("COPY_PATH", file.path)}
                  className="p-1 hover:text-indigo-300 hover:bg-dark-600 rounded"
                  title="Copy full path"
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

      {/* Chunk Inspector Modal */}
      {inspectingFile && (
        <ChunkInspector
          fileId={inspectingFile.id}
          filename={inspectingFile.name}
          onClose={() => setInspectingFile(null)}
        />
      )}
    </div>
  );
}
