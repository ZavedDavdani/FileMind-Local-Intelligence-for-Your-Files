import { useState, memo } from "react";
import { Folder, IntegrityMode } from "../types";
import {
  FolderPlus,
  Folder as FolderIcon,
  Trash2,
  Shield,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  HardDrive,
  AlertTriangle,
} from "lucide-react";

interface FolderManagerProps {
  folders: Folder[];
  onAddFolder: (path: string, recursive: boolean, mode: IntegrityMode, exclusions: string[]) => void;
  onUpdateFolder: (id: string, updates: Partial<Folder>) => void;
  onDeleteFolder: (id: string) => void;
  onRescanFolder: (id: string) => void;
  disabled?: boolean;
}

export const FolderManager = memo(function FolderManager({
  folders = [],
  onAddFolder,
  onUpdateFolder,
  onDeleteFolder,
  onRescanFolder,
  disabled,
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


  const handleSelectViaTauri = async () => {
    try {
      // Try Tauri native dialog if available
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
          <h2 className="text-sm font-semibold text-white">Registered Folders</h2>
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
              placeholder="e.g. C:\Users\Documents\Projects"
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              className="flex-1 bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono text-xs"
              autoFocus
            />
            <button
              type="button"
              onClick={handleSelectViaTauri}
              className="px-3 py-2 bg-dark-700 hover:bg-dark-600 text-slate-200 rounded-lg text-xs"
            >
              Browse...
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-1">
            {/* Integrity Mode Selector */}
            <div className="space-y-1">
              <label className="text-[11px] text-slate-400 font-medium">Integrity Verification Mode</label>
              <div className="flex space-x-1.5">
                <button
                  type="button"
                  onClick={() => setNewMode("NORMAL")}
                  className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium border flex items-center justify-center space-x-1 ${
                    newMode === "NORMAL"
                      ? "bg-indigo-950/70 border-indigo-500/60 text-indigo-300"
                      : "bg-dark-800 border-dark-600 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Shield className="w-3.5 h-3.5" />
                  <span>Normal (mtime)</span>
                </button>
                <button
                  type="button"
                  onClick={() => setNewMode("STRICT")}
                  className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium border flex items-center justify-center space-x-1 ${
                    newMode === "STRICT"
                      ? "bg-amber-950/70 border-amber-500/60 text-amber-300"
                      : "bg-dark-800 border-dark-600 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <ShieldAlert className="w-3.5 h-3.5" />
                  <span>Strict (SHA-256)</span>
                </button>
              </div>
            </div>

            {/* Recursive Checkbox */}
            <div className="space-y-1 flex flex-col justify-end">
              <label className="flex items-center space-x-2 cursor-pointer pb-2">
                <input
                  type="checkbox"
                  checked={newRecursive}
                  onChange={(e) => setNewRecursive(e.target.checked)}
                  className="rounded bg-dark-700 border-dark-600 text-indigo-600 focus:ring-0"
                />
                <span className="text-slate-300 text-xs">Recursive Subdirectory Traversal</span>
              </label>
            </div>
          </div>

          {/* Exclusions */}
          <div className="space-y-1">
            <label className="text-[11px] text-slate-400 font-medium">
              Custom Exclusions <span className="text-slate-500">(comma-separated globs, default noise excluded automatically)</span>
            </label>
            <input
              type="text"
              value={newExclusions}
              onChange={(e) => setNewExclusions(e.target.value)}
              className="w-full bg-dark-800 border border-dark-600 rounded-lg px-3 py-1.5 text-slate-100 font-mono text-xs focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end space-x-2 pt-2">
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="px-3 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg shadow-sm"
            >
              Register & Scan
            </button>
          </div>
        </form>
      )}

      {/* Folders List */}
      <div className="space-y-2.5">
        {safeFolders.length === 0 && !showAddForm && (
          <div className="py-6 text-center border border-dashed border-dark-600/70 rounded-xl text-slate-400 text-xs">
            No folders registered yet. Click <span className="text-indigo-400 font-medium">Add Folder</span> to begin tracking.
          </div>
        )}

        {safeFolders.map((f) => {
          const isExpanded = expandedFolderId === f.folder_id;

          return (
            <div
              key={f.folder_id}
              className="bg-dark-900/60 border border-dark-700/60 hover:border-dark-600 rounded-xl p-3.5 transition-all space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2.5 min-w-0">
                  <button
                    onClick={() => setExpandedFolderId(isExpanded ? null : f.folder_id)}
                    className="text-slate-400 hover:text-slate-200"
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                  </button>
                  <span className="font-mono text-xs text-slate-200 truncate" title={f.path}>
                    {f.path}
                  </span>
                </div>

                <div className="flex items-center space-x-2 shrink-0">
                  {/* Integrity Badge */}
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase border ${
                      f.integrity_mode === "STRICT"
                        ? "bg-amber-950/60 border-amber-500/40 text-amber-300"
                        : "bg-indigo-950/60 border-indigo-500/40 text-indigo-300"
                    }`}
                  >
                    {f.integrity_mode}
                  </span>

                  {/* Recursive Badge */}
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-dark-700 text-slate-300 border border-dark-600">
                    {f.recursive ? "Recursive" : "Top-Level"}
                  </span>

                  {/* Toggle Indexing Switch */}
                  <button
                    onClick={() => onUpdateFolder(f.folder_id, { indexing_enabled: !f.indexing_enabled })}
                    className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                      f.indexing_enabled
                        ? "bg-emerald-950/60 text-emerald-300 border border-emerald-500/40"
                        : "bg-slate-800 text-slate-400 border border-slate-700"
                    }`}
                  >
                    {f.indexing_enabled ? "Enabled" : "Paused"}
                  </button>

                  {/* Delete Button */}
                  <button
                    onClick={() => setFolderToDelete(f)}
                    className="p-1 text-slate-400 hover:text-rose-400 transition-colors"
                    title="Remove folder from index"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
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
                      className="px-2.5 py-1 bg-dark-700 hover:bg-dark-600 text-slate-200 rounded text-xs font-medium"
                    >
                      Force Full Rescan
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
                <p className="text-xs text-slate-400">Broad filesystem discovery and local intelligence indexing</p>
              </div>
            </div>

            {/* Warning Box */}
            <div className="bg-amber-950/30 border border-amber-500/30 rounded-xl p-3 flex items-start space-x-2.5 text-xs text-amber-200">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold text-amber-300">Resource & Time Notice</p>
                <p className="text-slate-300 leading-relaxed">
                  Full-system indexing scans your Windows storage environment (e.g. <code className="text-amber-300 font-mono">C:\Users</code>). This operation may consume significant CPU, RAM, disk I/O, and time depending on your drive size.
                </p>
              </div>
            </div>

            {/* Scope Information */}
            <div className="space-y-2 text-xs text-slate-300 bg-dark-800/60 border border-dark-700/60 rounded-xl p-3">
              <p className="font-medium text-slate-200">Indexing Scope & Security Boundaries:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Only supported document formats (PDF, DOCX, Markdown, Code, Spreadsheets, Text) up to 50 MB are indexed.</li>
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

