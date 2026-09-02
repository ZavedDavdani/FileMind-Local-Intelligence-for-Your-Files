import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  AskRequest,
  AskResponse,
  OllamaReadinessStatus,
} from "../types";
import { askFileMind, fetchAIStatus } from "../services/api";
import {
  Sparkles,
  Search,
  X,
  FileText,
  AlertTriangle,
  AlertCircle,
  Clock,
  Cpu,
  ExternalLink,
  ShieldCheck,
  Zap,
  Layers,
  ArrowRight,
  Copy,
  Check,
  History,
} from "lucide-react";

interface AskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onInspectChunk?: (fileId: string, filename: string, chunkId: string) => void;
}

export const AskModal: React.FC<AskModalProps> = ({
  isOpen,
  onClose,
  onInspectChunk,
}) => {
  const [query, setQuery] = useState("");
  const [quality, setQuality] = useState<"fast" | "quality">("fast");
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<OllamaReadinessStatus | null>(null);
  const [progressStage, setProgressStage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [queryHistory, setQueryHistory] = useState<string[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const readinessAbortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);
  const stageTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearStageTimers = useCallback(() => {
    stageTimersRef.current.forEach(clearTimeout);
    stageTimersRef.current = [];
  }, []);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);

      readinessAbortRef.current?.abort();
      const ctrl = new AbortController();
      readinessAbortRef.current = ctrl;

      fetchAIStatus(ctrl.signal)
        .then((res) => {
          if (res?.local_ai?.ollama) {
            setReadiness(res.local_ai.ollama);
          }
        })
        .catch(() => {
          // Non-blocking fallback
        });
    } else {
      clearStageTimers();
      setProgressStage(null);
      setCopied(false);
      abortControllerRef.current?.abort();
      readinessAbortRef.current?.abort();
      requestSeqRef.current++;
      setLoading(false);
    }
  }, [isOpen, clearStageTimers]);

  const handleCitationClick = useCallback(
    (citId: string) => {
      const isSelected = selectedCitationId === citId;
      const nextId = isSelected ? null : citId;
      setSelectedCitationId(nextId);

      if (nextId) {
        setTimeout(() => {
          const el = document.getElementById(`citation-card-${citId}`);
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        }, 50);
      }
    },
    [selectedCitationId]
  );

  const handleCopyAnswer = useCallback(async () => {
    if (!response?.answer) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(response.answer);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = response.answer;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("[AskModal] Failed to copy answer:", err);
    }
  }, [response?.answer]);

  const handleAsk = useCallback(
    async (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const q = query.trim();
      if (!q || loading) return;

      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const seq = ++requestSeqRef.current;

      clearStageTimers();
      setLoading(true);
      setError(null);
      setSelectedCitationId(null);
      setCopied(false);
      setProgressStage("Searching files…");

      // Record query in transient in-session history
      setQueryHistory((prev) => [q, ...prev.filter((h) => h.toLowerCase() !== q.toLowerCase())].slice(0, 10));

      // Phased progress timers reflecting pipeline stages
      const t1 = setTimeout(() => {
        if (seq === requestSeqRef.current) {
          setProgressStage("Preparing evidence…");
        }
      }, 250);

      const t2 = setTimeout(() => {
        if (seq === requestSeqRef.current) {
          setProgressStage("Generating local answer…");
        }
      }, 900);

      const t3 = setTimeout(() => {
        if (seq === requestSeqRef.current) {
          setProgressStage("Checking citations…");
        }
      }, 3200);

      stageTimersRef.current = [t1, t2, t3];

      try {
        const req: AskRequest = {
          query: q,
          mode: "hybrid",
          quality: quality,
          top_k: 10,
        };
        const res = await askFileMind(req, controller.signal);
        if (seq !== requestSeqRef.current || controller.signal.aborted) {
          return;
        }
        clearStageTimers();
        setProgressStage(null);
        setResponse(res);
      } catch (err: unknown) {
        clearStageTimers();
        setProgressStage(null);
        const isAbort = err instanceof Error && err.name === "AbortError";
        if (isAbort || seq !== requestSeqRef.current) {
          return;
        }
        console.error("[AskModal] Generation error:", err);
        const msg = err instanceof Error ? err.message : "Failed to generate answer";
        setError(msg);
      } finally {
        if (seq === requestSeqRef.current) {
          clearStageTimers();
          setProgressStage(null);
          setLoading(false);
        }
      }
    },
    [query, quality, loading, clearStageTimers]
  );

  if (!isOpen) return null;

  const renderStatusBadge = () => {
    if (!response) return null;

    const status = response.generation_status;
    if (status === "READY") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <ShieldCheck className="w-3.5 h-3.5" />
          Grounded Answer ({response.citations.length} sources)
        </span>
      );
    }
    if (status === "BUDGET_LIMITED") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
          <Layers className="w-3.5 h-3.5" />
          Budget-Limited Evidence
        </span>
      );
    }
    if (status === "NO_EVIDENCE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
          <AlertTriangle className="w-3.5 h-3.5" />
          Insufficient Evidence
        </span>
      );
    }
    if (status === "MODEL_UNAVAILABLE") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
          <AlertCircle className="w-3.5 h-3.5" />
          Local Model Unavailable
        </span>
      );
    }
    if (status === "TIMEOUT") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
          <Clock className="w-3.5 h-3.5" />
          Generation Timed Out
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
        <AlertCircle className="w-3.5 h-3.5" />
        {status}
      </span>
    );
  };

  // Parses answer text to render interactive clickable citation pills
  const renderFormattedAnswer = (text: string) => {
    if (!text) return null;
    const parts = text.split(/(\[E\d+\])/g);

    return (
      <div className="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">
        {parts.map((part, idx) => {
          const match = part.match(/^\[E(\d+)\]$/);
          if (match) {
            const citId = `E${match[1]}`;
            const exists = response?.citations.some((c) => c.citation_id === citId);
            const isSelected = selectedCitationId === citId;

            return (
              <button
                key={idx}
                type="button"
                onClick={() => handleCitationClick(citId)}
                className={`inline-flex items-center px-1.5 py-0.5 mx-0.5 text-xs font-mono font-bold rounded transition-colors ${
                  exists
                    ? isSelected
                      ? "bg-indigo-500 text-white shadow"
                      : "bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 border border-indigo-500/30"
                    : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                }`}
                title={exists ? `Inspect evidence for [${citId}]` : `Unresolved citation [${citId}]`}
                aria-label={`Citation ${citId}`}
              >
                [{citId}]
              </button>
            );
          }
          return <span key={idx}>{part}</span>;
        })}
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-dark-950/80 backdrop-blur-md animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="ask-modal-title"
    >
      <div className="relative w-full max-w-3xl max-h-[90vh] bg-dark-900 border border-slate-700/80 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-dark-800/40">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg border border-indigo-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 id="ask-modal-title" className="text-base font-semibold text-slate-100">
                  Ask FileMind
                </h2>
                {readiness && (
                  <div className="flex items-center">
                    {readiness.is_ollama_online && readiness.has_default_model ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        Local LLM Ready ({readiness.model_name})
                      </span>
                    ) : readiness.is_ollama_online && !readiness.has_default_model ? (
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        title={`Model '${readiness.model_name}' missing. Run 'ollama run ${readiness.model_name}'`}
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                        Model Missing ({readiness.model_name})
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20"
                        title="Ollama daemon is offline. Start it with 'ollama serve'"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        Ollama Offline
                      </span>
                    )}
                  </div>
                )}
              </div>
              <p className="text-xs text-slate-400">
                Grounded local file intelligence powered by Ollama ({response?.model_identity.model_name || readiness?.model_name || "qwen3:4b"})
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-dark-800 rounded-lg transition"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Proactive Guidance Banner if Ollama is offline or model is missing */}
        {readiness && !readiness.is_ollama_online && (
          <div className="px-6 py-2 bg-amber-500/10 border-b border-amber-500/20 text-xs text-amber-300 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>Ollama daemon is offline. Start it with <code className="px-1 py-0.5 bg-dark-950 rounded text-amber-200 font-mono text-[11px]">ollama serve</code> to enable local generation.</span>
          </div>
        )}
        {readiness && readiness.is_ollama_online && !readiness.has_default_model && (
          <div className="px-6 py-2 bg-rose-500/10 border-b border-rose-500/20 text-xs text-rose-300 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>Model <code className="px-1 py-0.5 bg-dark-950 rounded text-rose-200 font-mono text-[11px]">{readiness.model_name}</code> is not installed. Run <code className="px-1 py-0.5 bg-dark-950 rounded text-rose-200 font-mono text-[11px]">ollama run {readiness.model_name}</code>.</span>
          </div>
        )}

        {/* Query Input Section */}
        <form onSubmit={handleAsk} className="p-6 border-b border-slate-800 space-y-3 bg-dark-900/60">
          <div className="relative flex items-center">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a question about your indexed files... (e.g. How does vector storage work?)"
              maxLength={1000}
              className="w-full px-4 py-3 pl-11 bg-dark-800/90 border border-slate-700/70 rounded-xl text-slate-100 placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition shadow-inner"
              disabled={loading}
              aria-label="Ask query input"
            />
            <Search className="w-4 h-4 text-slate-400 absolute left-4 pointer-events-none" />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="absolute right-2 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-400 text-white text-xs font-semibold rounded-lg shadow transition flex items-center gap-1.5"
            >
              {loading ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>{progressStage || "Generating..."}</span>
                </>
              ) : (
                <>
                  <span>Ask</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </div>

          {/* Query History Chips */}
          {queryHistory.length > 0 && !loading && (
            <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
              <span className="text-[11px] text-slate-500 flex items-center gap-1">
                <History className="w-3 h-3 text-slate-500" />
                Recent:
              </span>
              {queryHistory.slice(0, 5).map((hQuery, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    setQuery(hQuery);
                    inputRef.current?.focus();
                  }}
                  className="px-2 py-0.5 bg-dark-800 hover:bg-dark-700 text-slate-400 hover:text-slate-200 border border-slate-700/50 rounded-full text-[11px] truncate max-w-[180px] transition"
                  title={hQuery}
                  aria-label={`Restore query: ${hQuery}`}
                >
                  {hQuery}
                </button>
              ))}
            </div>
          )}

          {/* Quality Mode Toggle */}
          <div className="flex items-center justify-between text-xs text-slate-400 pt-1">
            <div className="flex items-center gap-2">
              <span className="text-slate-400 font-medium">Retrieval Quality:</span>
              <div className="inline-flex p-0.5 bg-dark-800 rounded-lg border border-slate-700/60">
                <button
                  type="button"
                  onClick={() => setQuality("fast")}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition flex items-center gap-1 ${
                    quality === "fast"
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Zap className="w-3 h-3" />
                  Fast (~20ms)
                </button>
                <button
                  type="button"
                  onClick={() => setQuality("quality")}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition flex items-center gap-1 ${
                    quality === "quality"
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Layers className="w-3 h-3" />
                  Quality (Reranked)
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
              <span>100% Local • Zero Cloud Fallback</span>
            </div>
          </div>
        </form>

        {/* Modal Body / Answer / Citations */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5 min-h-[220px]">
          {/* Loading State with Staged Progress */}
          {loading && (
            <div
              className="py-12 flex flex-col items-center justify-center space-y-3 text-center"
              aria-live="polite"
              role="status"
            >
              <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-2xl border border-indigo-500/20">
                <Sparkles className="w-8 h-8 animate-spin" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-semibold text-slate-200 animate-pulse">
                  {progressStage || "Processing query…"}
                </p>
                <p className="text-xs text-slate-400">
                  Local Ollama synthesis with deterministic context budgeting
                </p>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {error && !loading && (
            <div className="p-4 bg-rose-950/40 border border-rose-500/30 rounded-xl flex items-start gap-3 text-rose-200 text-xs">
              <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-rose-300">Generation Error</p>
                <p className="mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {/* Model Unavailable Banner with Actionable Advice */}
          {response?.generation_status === "MODEL_UNAVAILABLE" && !loading && (
            <div className="p-4 bg-rose-950/40 border border-rose-500/30 rounded-xl flex items-start gap-3 text-rose-200 text-xs">
              <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-rose-300">Local AI Model Unavailable</p>
                <p className="mt-1 text-slate-300">
                  The local Ollama daemon is unreachable at{" "}
                  <code className="bg-rose-950 px-1 py-0.5 rounded font-mono text-rose-200">
                    http://127.0.0.1:11434
                  </code>
                  .
                </p>
                <div className="mt-2 text-[11px] text-slate-400 space-y-1">
                  <p>1. Start Ollama: <code className="text-indigo-300 font-mono">ollama serve</code></p>
                  <p>2. Verify model: <code className="text-indigo-300 font-mono">ollama run {response.model_identity.model_name}</code></p>
                </div>
              </div>
            </div>
          )}

          {/* Answer Card */}
          {response && !loading && response.generation_status !== "MODEL_UNAVAILABLE" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {renderStatusBadge()}
                </div>
                <div className="flex items-center gap-2">
                  {response.unresolved_citations && response.unresolved_citations.length > 0 && (
                    <span className="text-[11px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                      Unresolved keys: {response.unresolved_citations.join(", ")}
                    </span>
                  )}
                  {response.answer && (
                    <button
                      type="button"
                      onClick={handleCopyAnswer}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-slate-300 hover:text-white bg-dark-800 hover:bg-dark-700 border border-slate-700 rounded-lg transition shadow-sm"
                      aria-label="Copy generated answer to clipboard"
                      title="Copy Answer"
                    >
                      {copied ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="text-emerald-400">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5 text-slate-400" />
                          <span>Copy Answer</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>

              {/* Answer Content */}
              <div className="p-4 bg-dark-800/80 border border-slate-700/60 rounded-xl shadow-sm space-y-2">
                {renderFormattedAnswer(response.answer)}
              </div>

              {/* Citations & Evidence Section */}
              {response.citations && response.citations.length > 0 && (
                <div className="space-y-2.5 pt-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5 text-indigo-400" />
                      Verified Source Citations ({response.citations.length})
                    </h3>
                    <span className="text-[11px] text-slate-500">
                      Click citation to inspect provenance
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                    {response.citations.map((c) => {
                      const isSelected = selectedCitationId === c.citation_id;
                      return (
                        <div
                          key={c.citation_id}
                          id={`citation-card-${c.citation_id}`}
                          tabIndex={0}
                          role="button"
                          aria-label={`Citation [${c.citation_id}]: ${c.source_file}`}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              handleCitationClick(c.citation_id);
                            }
                          }}
                          onClick={() => handleCitationClick(c.citation_id)}
                          className={`p-3 rounded-xl border text-xs cursor-pointer transition flex flex-col justify-between space-y-2 ${
                            isSelected
                              ? "bg-indigo-950/40 border-indigo-500/60 shadow-md ring-1 ring-indigo-500/40"
                              : "bg-dark-800/50 hover:bg-dark-800 border-slate-700/50"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-1.5 overflow-hidden">
                              <span className="px-1.5 py-0.5 bg-indigo-500/20 text-indigo-300 font-mono font-bold rounded text-[11px]">
                                [{c.citation_id}]
                              </span>
                              <span className="font-medium text-slate-200 truncate" title={c.source_file}>
                                {c.source_file}
                              </span>
                            </div>
                            {c.score !== undefined && c.score !== null && (
                              <span className="text-[10px] text-slate-400 font-mono shrink-0">
                                score: {c.score.toFixed(2)}
                              </span>
                            )}
                          </div>

                          <div className="text-[11px] text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
                            {c.section && c.section !== "General" && (
                              <span>Sec: <strong className="text-slate-300">{c.section}</strong></span>
                            )}
                            {c.page !== null && c.page !== undefined && (
                              <span>Pg: <strong className="text-slate-300">{c.page}</strong></span>
                            )}
                            {c.line_start !== null && c.line_end !== null && (
                              <span>Lines: <strong className="text-slate-300">{c.line_start}-{c.line_end}</strong></span>
                            )}
                          </div>

                          {onInspectChunk && c.chunk_id && (
                            <div className="pt-1 flex justify-end">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onInspectChunk(c.file_id, c.source_file, c.chunk_id);
                                }}
                                className="inline-flex items-center gap-1 text-[11px] text-indigo-400 hover:text-indigo-300 font-medium"
                              >
                                <span>Inspect Evidence</span>
                                <ExternalLink className="w-3 h-3" />
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Empty / Initial State */}
          {!response && !loading && !error && (
            <div className="py-12 flex flex-col items-center justify-center text-center text-slate-400 space-y-2">
              <Sparkles className="w-8 h-8 text-indigo-400/50" />
              <p className="text-sm font-medium text-slate-300">
                Ask a question about your files
              </p>
              <p className="text-xs text-slate-500 max-w-md">
                FileMind retrieves evidence from your indexed documents and synthesizes a cited, local-only answer.
              </p>
            </div>
          )}
        </div>

        {/* Modal Footer / Telemetry */}
        <div className="px-6 py-3 border-t border-slate-800 bg-dark-800/60 flex items-center justify-between text-[11px] text-slate-400">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3 text-slate-500" />
              <span>Model: <strong className="text-slate-300">{response?.model_identity.model_name || "qwen3:4b"}</strong></span>
            </span>
            {response?.retrieval_metadata.latency_breakdown_ms?.total_request !== undefined && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3 text-slate-500" />
                <span>Search: <strong>{response.retrieval_metadata.latency_breakdown_ms.total_request.toFixed(1)}ms</strong></span>
              </span>
            )}
            {response?.context_budget?.evidence_used !== undefined && (
              <span className="hidden sm:inline">
                Context: <strong>{response.context_budget.evidence_used} tokens</strong>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <kbd className="px-1.5 py-0.5 bg-dark-700 border border-slate-600 rounded font-mono text-[10px] text-slate-300">
              Esc
            </kbd>
            <span>to close</span>
          </div>
        </div>
      </div>
    </div>
  );
};
