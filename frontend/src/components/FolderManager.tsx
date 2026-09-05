import { useState, memo } from "react";
import { Folder, IntegrityMode } from "../types";
import {
  FolderPlus,
  FilePlus,
  Folder as FolderIcon,
  Trash2,
  Shield,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  HardDrive,
  AlertTriangle,
  Loader2,
} from "lucide-react";

interface FolderManagerProps {
  folders: Folder[];
  onAddFolder: (path: string, recursive: boolean, mode: IntegrityMode, exclusions: string[]) => void;
  onAddFiles?: (paths: string[]) => void;
  onUpdateFolder: (id: string, updates: Partial<Folder>) => void;
  onDeleteFolder: (id: string) => void;
  onRescanFolder: (id: string) => void;
  disabled?: boolean;
  activeAction?: { type: "deleting" | "rescanning" | "adding"; targetId?: string } | null;
}

export const FolderManager = memo(function FolderManager({
  folders = [],
  onAddFolder,
  onAddFiles,
  onUpdateFolder,
  onDeleteFolder,
  onRescanFolder,
  disabled,
  activeAction,
}: FolderManagerProps) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [showFullSystemModal, setShowFullSystemModal] = useState(false);
  const [systemRootPath, setSystemRootPath] = useState("C:\\Users");
  const [newPath, setNewPath] = useState("");
  const [newRecursive, setNewRecursive] = useState(true);
  const [newMode, setNewMode] = useState<IntegrityMode>("NORMAL");
  const [newExclusions, setNewExclusions] = useState("*.tmp, *.log");
  const [expandedFolderId, setExpandedFolderId] = useState<string | null>(null);
  const [folderToDelete, setFolderToDelete] = useState<Folder | null>(null);

  const safeFolders = Array.isArray(folders) ? folders : [];

  const handleSelectFolderViaTauri = async () => {
    try {
      const dialog = await import("@tauri-apps/plugin-dialog");
      const selected = await dialog.open({
        directory: true,
        multiple: false,
        title: "Select Folder to Index with FileMind",
      });
      if (selected && typeof selected === "string") {
        setNewPath(selected);
      }
    } catch {
      // Fallback: user types or pastes path
    }
  };

  const handleSelectFilesViaTauri = async () => {
    try {
      const dialog = await import("@tauri-apps/plugin-dialog");
      const selected = await dialog.open({
        directory: false,
        multiple: true,
        title: "Select Files to Index with FileMind",
      });
      if (selected) {
        const paths = Array.isArray(selected) ? selected : [selected];
        const validPaths = paths.filter((p): p is string => typeof p === "string" && Boolean(p.trim()));
        if (validPaths.length > 0 && onAddFiles) {
          onAddFiles(validPaths);
        }
      }
    } catch (err) {
      console.error("Native file picker error:", err);
    }
  };

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim()) return;

    const patterns = newExclusions
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);

    onAddFolder(newPath.trim(), newRecursive, newMode, patterns);
    setNewPath("");
    setShowAddForm(false);
  };

  const handleFullSystemSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!systemRootPath.trim()) return;

    // Standard high-noise system exclusions for broad root scans
    const systemExclusions = [
      "*.tmp",
      "*.log",
      "AppData",
      "Windows",
      "Program Files",
      "Program Files (x86)",
      "node_modules",
      ".git",
      ".venv",
      "$Recycle.Bin",
      "System Volume Information",
    ];

    onAddFolder(systemRootPath.trim(), true, "NORMAL", systemExclusions);
    setShowFullSystemModal(false);
  };

  return (
    <div className="bg-dark-800/60 border border-dark-700/60 rounded-2xl p-5 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2.5">
          <FolderIcon className="w-5 h-5 text-indigo-400" />
          <h2 className="text-sm font-semibold text-white">Registered Folders & Files</h2>
          <span className="text-xs bg-dark-700 px-2 py-0.5 rounded-full text-slate-300 font-mono">
            {safeFolders.length}
          </span>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setShowFullSystemModal(true)}
            disabled={disabled}
            aria-label="Index Full System"
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-dark-700 hover:bg-dark-600 disabled:opacity-50 text-slate-200 hover:text-white text-xs font-medium border border-dark-600 transition-colors shadow-sm"
            title="Index all files across your Windows user environment"
          >
            <HardDrive className="w-4 h-4 text-purple-400" />
            <span>Index Full System</span>
          </button>

          <button
            onClick={handleSelectFilesViaTauri}
            disabled={disabled || activeAction?.type === "adding"}
            aria-label="Add Files"
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium transition-colors shadow-sm"
            title="Select individual files to index without scanning their parent folder"
          >
            {activeAction?.type === "adding" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FilePlus className="w-4 h-4" />
            )}
            <span>Add Files</span>
          </button>

          <button
            onClick={() => setShowAddForm(!showAddForm)}
            disabled={disabled}
            aria-label="Add Folder"
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-medium transition-colors shadow-sm"
          >
            <FolderPlus className="w-4 h-4" />
            <span>Add Folder</span>
          </button>
        </div>
      </div>

      {/* Add Folder Modal / Drawer */}
      {showAddForm && (
        <form
          onSubmit={handleAddSubmit}
          className="bg-dark-900/80 border border-indigo-500/30 rounded-xl p-4 space-y-3.5 transition-all text-xs"
        >
          <p className="font-semibold text-indigo-300 text-xs">Register New Folder for Indexing</p>
          
          <div className="flex space-x-2">
            <input
              type="text"
              placeholder="e.g. C:\\Users\\Documents\\Projects"
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              className="flex-1 bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono text-xs"
              autoFocus
            />
            <button
              type="button"
              onClick={handleSelectFolderViaTauri}
              className="px-3 py-2 bg-dark-700 hover:bg-dark-600 text-slate-200 rounded-lg text-xs"
            >
              Browse...
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-1">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={newRecursive}
                onChange={(e) => setNewRecursive(e.target.checked)}
                className="rounded bg-dark-800 border-dark-600 text-indigo-600 focus:ring-0"
              />
              <span className="text-slate-300">Recursive Discovery</span>
            </label>

            <div className="flex items-center space-x-2">
              <span className="text-slate-400">Integrity Policy:</span>
              <select
                value={newMode}
                onChange={(e) => setNewMode(e.target.value as IntegrityMode)}
                className="bg-dark-800 border border-dark-600 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="NORMAL">Normal (Fast Path)</option>
                <option value="STRICT">Strict (Full SHA-256)</option>
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-[11px] text-slate-400 font-medium">Custom Glob Exclusions</label>
            <input
              type="text"
              placeholder="*.tmp, *.log, build, target"
              value={newExclusions}
              onChange={(e) => setNewExclusions(e.target.value)}
              className="w-full bg-dark-800 border border-dark-600 rounded-lg px-3 py-1.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono text-xs"
            />
          </div>

          <div className="flex justify-end space-x-2 pt-2 border-t border-dark-800">
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="px-3 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 rounded-lg text-xs font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!newPath.trim()}
              className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors shadow-sm"
            >
              Start Indexing
            </button>
          </div>
        </form>
      )}

      {/* Folders List */}
      <div className="space-y-2">
        {safeFolders.length === 0 && (
          <div className="py-8 text-center text-xs text-slate-500 bg-dark-900/40 rounded-xl border border-dashed border-dark-700">
            No folders or files registered yet. Click <span className="text-indigo-400 font-semibold">+ Add Folder</span> or <span className="text-emerald-400 font-semibold">+ Add Files</span> to get started.
          </div>
        )}

        {safeFolders.map((f) => {
          const isExpanded = expandedFolderId === f.folder_id;
          const isDeleting = activeAction?.type === "deleting" && activeAction?.targetId === f.folder_id;
          const isRescanning = activeAction?.type === "rescanning" && activeAction?.targetId === f.folder_id;

          return (
            <div
              key={f.folder_id}
              className="bg-dark-900/50 border border-dark-700/50 rounded-xl p-3 space-y-2.5 transition-all hover:border-dark-600"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3 overflow-hidden">
                  <button
                    onClick={() => setExpandedFolderId(isExpanded ? null : f.folder_id)}
                    className="text-slate-400 hover:text-white transition-colors"
                  >
                    {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                  </button>

                  <div className="space-y-0.5 min-w-0">
                    <p className="font-mono text-xs text-slate-200 truncate font-medium">{f.path}</p>
                    <div className="flex items-center space-x-2 text-[11px] text-slate-500">
                      <span>{f.recursive ? "Recursive" : "Top-level only"}</span>
                      <span>•</span>
                      <span className="flex items-center space-x-1">
                        {f.integrity_mode === "STRICT" ? (
                          <>
                            <ShieldAlert className="w-3 h-3 text-amber-400" />
                            <span className="text-amber-400">Strict (SHA-256)</span>
                          </>
                        ) : (
                          <>
                            <Shield className="w-3 h-3 text-indigo-400" />
                            <span>Normal</span>
                          </>
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <button
                    onClick={() =>
                      onUpdateFolder(f.folder_id, {
                        indexing_enabled: !f.indexing_enabled,
                      })
                    }
                    className={`px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                      f.indexing_enabled
                        ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                        : "bg-slate-800 border-slate-700 text-slate-500"
                    }`}
                  >
                    {f.indexing_enabled ? "Active" : "Paused"}
                  </button>

                  <button
                    onClick={() => setFolderToDelete(f)}
                    disabled={isDeleting || isRescanning}
                    className="p-1 text-slate-400 hover:text-rose-400 disabled:opacity-50 transition-colors"
                    title="Remove folder from index"
                  >
                    {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* Expanded Settings */}
              {isExpanded && (
                <div className="pt-2 border-t border-dark-700/60 grid grid-cols-3 gap-3 text-[11px] text-slate-400">
                  <div>
                    <span className="block text-slate-500">Integrity Policy</span>
                    <button
                      onClick={() =>
                        onUpdateFolder(f.folder_id, {
                          integrity_mode: f.integrity_mode === "NORMAL" ? "STRICT" : "NORMAL",
                        })
                      }
                      className="mt-0.5 text-indigo-400 hover:underline"
                    >
                      Switch to {f.integrity_mode === "NORMAL" ? "Strict (Full SHA-256)" : "Normal (Fast Path)"}
                    </button>
                  </div>

                  <div>
                    <span className="block text-slate-500">Exclusions</span>
                    <span className="font-mono text-[10px] text-slate-300">
                      {f.exclude_patterns.length > 0 ? f.exclude_patterns.join(", ") : "Default only"}
                    </span>
                  </div>

                  <div className="flex justify-end items-center">
                    <button
                      onClick={() => onRescanFolder(f.folder_id)}
                      disabled={isRescanning || isDeleting}
                      className="flex items-center space-x-1 px-2.5 py-1 bg-dark-700 hover:bg-dark-600 disabled:opacity-50 text-slate-200 rounded text-xs font-medium transition-colors"
                    >
                      {isRescanning && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                      <span>{isRescanning ? "Rescanning..." : "Force Full Rescan"}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Delete Folder Confirmation Dialog */}
      {folderToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
          <div className="bg-dark-900 border border-dark-700 rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center space-x-3 text-rose-400">
              <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Remove Registered Folder?</h3>
                <p className="text-xs text-slate-400">This will remove the folder from FileMind's index.</p>
              </div>
            </div>

            <div className="bg-dark-800/80 border border-dark-700/60 rounded-xl p-3 space-y-1">
              <span className="text-[11px] text-slate-400 font-medium">Folder Path</span>
              <p className="font-mono text-xs text-slate-200 break-all">{folderToDelete.path}</p>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              All indexed file metadata, text chunks, and vector embeddings for files in this folder will be safely purged from the local index.
              <span className="block mt-1 text-slate-300 font-medium">Your original files on disk will NOT be modified or deleted.</span>
            </p>

            <div className="flex justify-end space-x-2 pt-2 border-t border-dark-800">
              <button
                type="button"
                onClick={() => setFolderToDelete(null)}
                className="px-3 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 rounded-lg text-xs font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  onDeleteFolder(folderToDelete.folder_id);
                  setFolderToDelete(null);
                }}
                className="px-4 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium transition-colors shadow-sm"
              >
                Remove Folder
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Index Full System Confirmation Dialog */}
      {showFullSystemModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Index Full System Confirmation"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm"
        >
          <div className="bg-dark-900 border border-purple-500/30 rounded-2xl max-w-lg w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center space-x-3 text-purple-400">
              <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20">
                <HardDrive className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Index Full System (Windows)</h3>
                <p className="text-xs text-slate-400">Broad filesystem discovery across your user environment</p>
              </div>
            </div>

            {/* Warning Box */}
            <div className="bg-amber-950/30 border border-amber-500/30 rounded-xl p-3 flex items-start space-x-2.5 text-xs text-amber-200">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold text-amber-300">Resource & Time Notice</p>
                <p className="text-slate-300 leading-relaxed">
                  Full-system indexing scans your selected storage environment (e.g. <code className="text-amber-300 font-mono">C:\\Users</code>). This operation may consume CPU, RAM, and disk I/O depending on your drive size.
                </p>
              </div>
            </div>

            {/* Scope Information */}
            <div className="space-y-2 text-xs text-slate-300 bg-dark-800/60 border border-dark-700/60 rounded-xl p-3">
              <p className="font-medium text-slate-200">Indexing Scope & Security Boundaries:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Supported document and media formats up to the 50 MB default limit (PDF, DOCX/DOC, PPTX/PPT, XLSX/CSV/TSV, Code, Markdown/TXT/HTML/RTF, Images with OCR, Audio/Video with Whisper transcripts) are indexed.</li>
                <li>Only folders and individual files explicitly selected or registered by you are eligible for indexing.</li>
                <li>System directories, AppData, Windows, Program Files, <code className="text-indigo-300">node_modules</code>, and caches are automatically excluded.</li>
                <li>You can Pause, Resume, or Cancel indexing at any time via Indexing Controls.</li>
              </ul>
            </div>

            {/* Path Configuration */}
            <form onSubmit={handleFullSystemSubmit} className="space-y-3">
              <div className="space-y-1">
                <label className="text-[11px] text-slate-400 font-medium">System / User Storage Root</label>
                <input
                  type="text"
                  value={systemRootPath}
                  onChange={(e) => setSystemRootPath(e.target.value)}
                  className="w-full bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500 font-mono text-xs"
                />
              </div>

              <div className="flex justify-end space-x-2 pt-2 border-t border-dark-800">
                <button
                  type="button"
                  onClick={() => setShowFullSystemModal(false)}
                  className="px-3 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 rounded-lg text-xs font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-xs font-medium transition-colors shadow-sm"
                >
                  Start Full System Indexing
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
});
