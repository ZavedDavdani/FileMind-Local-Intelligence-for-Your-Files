import React, { useState } from "react";
import { Copy, ExternalLink, FolderOpen, Check } from "lucide-react";
import { executeSafeAction } from "../services/api";

interface SafeActionsProps {
  filePath: string;
  onNotification?: (msg: string) => void;
}

export const SafeActions: React.FC<SafeActionsProps> = ({ filePath, onNotification }) => {
  const [copied, setCopied] = useState(false);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const handleOpenFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setLoadingAction("open");
    try {
      await executeSafeAction("OPEN_FILE", filePath);
      onNotification?.(`Opened file: ${filePath}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to open file";
      onNotification?.(`Error: ${msg}`);
    } finally {
      setLoadingAction(null);
    }
  };

  const handleOpenFolder = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setLoadingAction("folder");
    try {
      await executeSafeAction("OPEN_FOLDER", filePath);
      onNotification?.(`Revealed in Explorer: ${filePath}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to open folder";
      onNotification?.(`Error: ${msg}`);
    } finally {
      setLoadingAction(null);
    }
  };

  const handleCopyPath = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await executeSafeAction("COPY_PATH", filePath);
      await navigator.clipboard.writeText(res.target_path || filePath);
      setCopied(true);
      onNotification?.("Path copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch (err: unknown) {
      // Fallback direct clipboard copy
      try {
        await navigator.clipboard.writeText(filePath);
        setCopied(true);
        onNotification?.("Path copied to clipboard");
        setTimeout(() => setCopied(false), 2000);
      } catch (clipErr) {
        onNotification?.("Failed to copy path");
      }
    }
  };

  return (
    <div className="flex items-center space-x-1.5 opacity-90 group-hover:opacity-100 transition-opacity">
      <button
        onClick={handleOpenFile}
        disabled={loadingAction !== null}
        className="inline-flex items-center space-x-1 px-2 py-1 rounded bg-dark-700 hover:bg-dark-600 active:bg-dark-500 text-[11px] font-medium text-slate-200 border border-dark-600/80 transition-colors"
        title="Open File with default application"
      >
        <ExternalLink className="w-3 h-3 text-blue-400" />
        <span>Open</span>
      </button>

      <button
        onClick={handleOpenFolder}
        disabled={loadingAction !== null}
        className="inline-flex items-center space-x-1 px-2 py-1 rounded bg-dark-700 hover:bg-dark-600 active:bg-dark-500 text-[11px] font-medium text-slate-200 border border-dark-600/80 transition-colors"
        title="Reveal in File Explorer"
      >
        <FolderOpen className="w-3 h-3 text-amber-400" />
        <span>Folder</span>
      </button>

      <button
        onClick={handleCopyPath}
        className="inline-flex items-center space-x-1 px-2 py-1 rounded bg-dark-700 hover:bg-dark-600 active:bg-dark-500 text-[11px] font-medium text-slate-200 border border-dark-600/80 transition-colors"
        title="Copy canonical path to clipboard"
      >
        {copied ? (
          <>
            <Check className="w-3 h-3 text-emerald-400" />
            <span className="text-emerald-300">Copied</span>
          </>
        ) : (
          <>
            <Copy className="w-3 h-3 text-slate-400" />
            <span>Copy Path</span>
          </>
        )}
      </button>
    </div>
  );
};
