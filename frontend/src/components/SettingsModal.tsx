import React, { useState, useEffect, useCallback } from "react";
import {
  Settings as SettingsIcon,
  Cpu,
  Database,
  Activity,
  RotateCw,
  HardDrive,
  ShieldCheck,
} from "lucide-react";
import {
  fetchModelStatus,
  selectChatModel,
  fetchStorageStats,
  fetchDiagnostics,
} from "../services/api";
import {
  ModelStatusResponse,
  StorageStatsResponse,
  DiagnosticsResponse,
} from "../types";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNotify: (msg: string) => void;
}

type SettingsTab = "MODELS" | "STORAGE" | "DIAGNOSTICS";

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  onNotify,
}) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>("MODELS");
  const [modelStatus, setModelStatus] = useState<ModelStatusResponse | null>(null);
  const [storageStats, setStorageStats] = useState<StorageStatsResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSelectingModel, setIsSelectingModel] = useState(false);

  const loadAll = useCallback(async () => {
    setIsLoading(true);
    try {
      const [m, s, d] = await Promise.all([
        fetchModelStatus().catch(() => null),
        fetchStorageStats().catch(() => null),
        fetchDiagnostics().catch(() => null),
      ]);
      if (m) setModelStatus(m);
      if (s) setStorageStats(s);
      if (d) setDiagnostics(d);
    } catch (err: any) {
      console.error("Failed to load settings data", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadAll();
    }
  }, [isOpen, loadAll]);

  if (!isOpen) return null;

  const handleSelectModel = async (modelName: string) => {
    setIsSelectingModel(true);
    try {
      await selectChatModel(modelName);
      onNotify(`Active chat model set to ${modelName}`);
      await loadAll();
    } catch (err: any) {
      onNotify(`Failed to set model: ${err.message}`);
    } finally {
      setIsSelectingModel(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-dark-850 border border-slate-700 rounded-2xl w-full max-w-3xl h-[600px] shadow-2xl flex flex-col overflow-hidden">
        {/* Modal Header */}
        <div className="px-6 py-4 bg-dark-800 border-b border-slate-700 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-900/40 border border-purple-500/30 rounded-xl text-purple-400">
              <SettingsIcon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-slate-100">FileMind Settings & System</h2>
              <p className="text-[11px] text-slate-400">
                100% Local AI Models, Storage Breakdown, and Diagnostics
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg text-sm"
          >
            ✕
          </button>
        </div>

        {/* Body Grid: Sidebar tabs + Content area */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Navigation Sidebar */}
          <div className="w-56 bg-dark-900 border-r border-slate-800 p-3 space-y-1 shrink-0">
            <button
              onClick={() => setActiveTab("MODELS")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition ${
                activeTab === "MODELS"
                  ? "bg-purple-600/20 text-purple-200 border border-purple-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
              }`}
            >
              <Cpu className="w-4 h-4 text-purple-400" />
              <span>Models & AI Engine</span>
            </button>

            <button
              onClick={() => setActiveTab("STORAGE")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition ${
                activeTab === "STORAGE"
                  ? "bg-purple-600/20 text-purple-200 border border-purple-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
              }`}
            >
              <HardDrive className="w-4 h-4 text-cyan-400" />
              <span>Storage & Database</span>
            </button>

            <button
              onClick={() => setActiveTab("DIAGNOSTICS")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition ${
                activeTab === "DIAGNOSTICS"
                  ? "bg-purple-600/20 text-purple-200 border border-purple-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-dark-800"
              }`}
            >
              <Activity className="w-4 h-4 text-emerald-400" />
              <span>System Diagnostics</span>
            </button>
          </div>

          {/* Tab Content Panel */}
          <div className="flex-1 overflow-y-auto p-6 bg-dark-850">
            {isLoading ? (
              <div className="h-full flex items-center justify-center text-purple-400 gap-2">
                <RotateCw className="w-5 h-5 animate-spin" />
                <span className="text-xs">Loading settings data...</span>
              </div>
            ) : (
              <>
                {/* ================= TAB 1: MODELS ================= */}
                {activeTab === "MODELS" && (
                  <div className="space-y-5">
                    {/* Ollama Status Card */}
                    <div className="bg-dark-900 border border-slate-700/80 rounded-xl p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span
                            className={`w-2.5 h-2.5 rounded-full ${
                              modelStatus?.is_ollama_online ? "bg-emerald-500" : "bg-amber-500"
                            }`}
                          />
                          <h3 className="text-xs font-semibold text-slate-100">
                            Local Ollama LLM Service
                          </h3>
                        </div>
                        <span className="text-[11px] font-mono text-slate-400">
                          {modelStatus?.endpoint || "http://127.0.0.1:11434"}
                        </span>
                      </div>

                      <p className="text-xs text-slate-400 leading-relaxed">
                        {modelStatus?.is_ollama_online
                          ? "Ollama is active and responding locally. Grounded chat and synthesis will use your local LLM."
                          : "Ollama is offline. FileMind continues to index, search, and extract verified evidence locally without interruption."}
                      </p>
                    </div>

                    {/* Active Model Selector */}
                    <div className="space-y-3">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Select Active Chat Model
                      </h4>
                      {modelStatus && modelStatus.available_models.length > 0 ? (
                        <div className="space-y-2">
                          {modelStatus.available_models.map((m) => {
                            const isSelected = m === modelStatus.active_chat_model;
                            return (
                              <div
                                key={m}
                                onClick={() => !isSelectingModel && handleSelectModel(m)}
                                className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition ${
                                  isSelected
                                    ? "bg-purple-950/60 border-purple-500 text-purple-100"
                                    : "bg-dark-900 border-slate-800 hover:border-slate-700 text-slate-300"
                                }`}
                              >
                                <div className="flex items-center gap-2.5">
                                  <Cpu className="w-4 h-4 text-purple-400" />
                                  <div>
                                    <p className="text-xs font-semibold">{m}</p>
                                    <p className="text-[10px] text-slate-400">Local GGUF / Ollama Model</p>
                                  </div>
                                </div>
                                {isSelected && (
                                  <span className="px-2 py-0.5 bg-purple-600 text-white rounded text-[10px] font-medium">
                                    Active
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="bg-dark-900 border border-slate-800 rounded-xl p-4 text-xs text-slate-400">
                          No Ollama models detected. Run <code className="text-purple-300 bg-dark-800 px-1 py-0.5 rounded font-mono">ollama pull llama3.2</code> in your terminal to enable chat synthesis.
                        </div>
                      )}
                    </div>

                    {/* Built-in Local Embeddings & Reranker */}
                    <div className="space-y-3 pt-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Built-in Vector & Reranking Components
                      </h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div className="bg-dark-900 border border-slate-800 rounded-xl p-3.5 space-y-1">
                          <span className="text-[11px] font-medium text-slate-400">Embedding Model</span>
                          <p className="text-xs font-semibold text-slate-200">
                            {modelStatus?.active_embedding_model || "BAAI/bge-small-en-v1.5"}
                          </p>
                          <span className="text-[10px] text-emerald-400">384-dim ONNX • CPU Optimized</span>
                        </div>

                        <div className="bg-dark-900 border border-slate-800 rounded-xl p-3.5 space-y-1">
                          <span className="text-[11px] font-medium text-slate-400">Reranker Model</span>
                          <p className="text-xs font-semibold text-slate-200">
                            {modelStatus?.active_reranker_model || "ms-marco-MiniLM-L-6-v2"}
                          </p>
                          <span className="text-[10px] text-purple-400">Cross-Encoder • Local</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* ================= TAB 2: STORAGE ================= */}
                {activeTab === "STORAGE" && (
                  <div className="space-y-5">
                    {/* Database Location */}
                    <div className="bg-dark-900 border border-slate-700/80 rounded-xl p-4 space-y-2">
                      <div className="flex items-center gap-2">
                        <Database className="w-4 h-4 text-cyan-400" />
                        <h3 className="text-xs font-semibold text-slate-100">
                          Local Database Storage
                        </h3>
                      </div>
                      <p className="text-xs font-mono text-slate-300 break-all bg-dark-800 p-2.5 rounded-lg border border-slate-800">
                        {storageStats?.db_path || "%APPDATA%\\FileMind\\filemind.db"}
                      </p>
                    </div>

                    {/* Storage Metric Cards */}
                    {storageStats && (
                      <div className="grid grid-cols-2 gap-4">
                        <div className="bg-dark-900 border border-slate-800 rounded-xl p-4">
                          <span className="text-xs font-medium text-slate-400">Database Size</span>
                          <p className="text-xl font-bold text-white mt-1">
                            {storageStats.database_size_mb.toFixed(2)} MB
                          </p>
                          <span className="text-[10px] text-slate-500">
                            {(storageStats.database_size_bytes / 1024).toFixed(0)} KB on disk
                          </span>
                        </div>

                        <div className="bg-dark-900 border border-slate-800 rounded-xl p-4">
                          <span className="text-xs font-medium text-slate-400">Total Storage Footprint</span>
                          <p className="text-xl font-bold text-cyan-400 mt-1">
                            {storageStats.total_storage_mb.toFixed(2)} MB
                          </p>
                          <span className="text-[10px] text-slate-500">
                            FTS5 + sqlite-vec tables
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Privacy Guarantee */}
                    <div className="bg-emerald-950/30 border border-emerald-500/30 rounded-xl p-4 flex items-start gap-3">
                      <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                      <div>
                        <h4 className="text-xs font-semibold text-emerald-300">
                          100% Local-First Data Privacy
                        </h4>
                        <p className="text-[11px] text-emerald-200/80 mt-0.5 leading-relaxed">
                          All files, parsed text, lexical indexes, vector embeddings, and chat histories remain strictly on your local machine. No telemetry or cloud analytics are executed.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* ================= TAB 3: DIAGNOSTICS ================= */}
                {activeTab === "DIAGNOSTICS" && (
                  <div className="space-y-4">
                    <div className="bg-dark-900 border border-slate-800 rounded-xl divide-y divide-slate-800 text-xs">
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">Operating System</span>
                        <span className="font-mono text-slate-200">{diagnostics?.system_os || "Windows"}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">Application Version</span>
                        <span className="font-mono text-purple-400 font-semibold">{diagnostics?.app_version || "0.1.0"}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">Schema Migration Version</span>
                        <span className="font-mono text-slate-200">V{diagnostics?.schema_version || 10}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">SQLite Engine</span>
                        <span className="font-mono text-slate-200">{diagnostics?.sqlite_version || "3.x"}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">sqlite-vec Extension</span>
                        <span className="font-mono text-emerald-400">{diagnostics?.vec_version || "Loaded"}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">Active Watcher Folders</span>
                        <span className="font-mono text-slate-200">{diagnostics?.total_folders_watched || 0}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-400">Indexed Files Count</span>
                        <span className="font-mono text-slate-200">{diagnostics?.indexed_file_count || 0}</span>
                      </div>
                    </div>

                    {diagnostics?.recent_errors && diagnostics.recent_errors.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-rose-400">Recent Diagnostic Logs</h4>
                        <div className="bg-dark-950 border border-rose-900/50 rounded-xl p-3 text-[11px] font-mono text-rose-300 space-y-1 max-h-36 overflow-y-auto">
                          {diagnostics.recent_errors.map((err, idx) => (
                            <div key={idx}>• {err}</div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
