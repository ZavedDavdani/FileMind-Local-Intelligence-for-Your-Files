import React from "react";
import { Folder, FolderSearch, RefreshCw, Layers, Timer } from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";

interface FolderPickerProps {
  selectedFolder: string | null;
  fileCount: number;
  scanDurationMs: number | null;
  isScanning: boolean;
  onSelectFolder: (folderPath: string) => void;
  onRescan: () => void;
  disabled?: boolean;
}

export const FolderPicker: React.FC<FolderPickerProps> = ({
  selectedFolder,
  fileCount,
  scanDurationMs,
  isScanning,
  onSelectFolder,
  onRescan,
  disabled,
}) => {
  const handleOpenFolderDialog = async () => {
    try {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Select Folder to Enumerate - FileMind Smoke Test",
      });

      if (selected && typeof selected === "string") {
        onSelectFolder(selected);
      }
    } catch (err) {
      console.warn("Tauri dialog error, prompting fallback prompt", err);
      const fallback = window.prompt("Enter folder path:", selectedFolder || "C:\\");
      if (fallback) {
        onSelectFolder(fallback);
      }
    }
  };

  return (
    <div className="bg-dark-800/40 border border-dark-700/60 rounded-xl p-5 shadow-inner">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center space-x-2 text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
            <FolderSearch className="w-3.5 h-3.5 text-blue-400" />
            <span>Target Directory</span>
          </div>

          <div className="flex items-center space-x-2">
            <div className="p-2 rounded-lg bg-dark-700/60 border border-dark-600/50 text-slate-300">
              <Folder className="w-4 h-4 text-blue-400" />
            </div>
            <div className="truncate font-mono text-sm text-slate-200" title={selectedFolder || "None selected"}>
              {selectedFolder ? (
                <span className="text-white font-medium">{selectedFolder}</span>
              ) : (
                <span className="text-slate-500 italic">No folder selected yet</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3 self-start md:self-center">
          <button
            onClick={handleOpenFolderDialog}
            disabled={disabled || isScanning}
            className="flex items-center space-x-2 px-4 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-500 active:bg-brand-700 disabled:opacity-50 text-xs font-semibold text-white shadow-lg shadow-blue-500/20 transition-all cursor-pointer"
          >
            <FolderSearch className="w-4 h-4" />
            <span>Select Folder</span>
          </button>

          {selectedFolder && (
            <button
              onClick={onRescan}
              disabled={disabled || isScanning}
              className="flex items-center space-x-1.5 px-3 py-2.5 rounded-lg bg-dark-700 hover:bg-dark-600 active:bg-dark-500 disabled:opacity-50 text-xs font-medium text-slate-200 border border-dark-600 transition-colors"
              title="Rescan directory"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? "animate-spin text-blue-400" : ""}`} />
              <span>Rescan</span>
            </button>
          )}
        </div>
      </div>

      {selectedFolder && (
        <div className="mt-4 pt-3.5 border-t border-dark-700/50 flex flex-wrap items-center gap-5 text-xs text-slate-400">
          <div className="flex items-center space-x-1.5">
            <Layers className="w-3.5 h-3.5 text-blue-400" />
            <span>Discovered Files:</span>
            <span className="font-semibold text-slate-100">{fileCount}</span>
          </div>

          <div className="flex items-center space-x-1.5">
            <Timer className="w-3.5 h-3.5 text-emerald-400" />
            <span>Scan Duration:</span>
            <span className="font-semibold text-slate-100 font-mono">
              {scanDurationMs !== null ? `${scanDurationMs} ms` : "—"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
