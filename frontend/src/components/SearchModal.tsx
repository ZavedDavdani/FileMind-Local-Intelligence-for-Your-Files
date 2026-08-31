import React, { useState, useEffect, useRef } from "react";
import { SearchRequest, SearchResponse, Folder } from "../types";
import { searchEvidence, executeSafeAction } from "../services/api";

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  folders: Folder[];
  onInspectChunk?: (chunkId: string) => void;
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  folders,
  onInspectChunk,
}) => {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"hybrid" | "bm25" | "dense">("hybrid");
  const [selectedFolder, setSelectedFolder] = useState<string>("");
  const [selectedExt, setSelectedExt] = useState<string>("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; msg: string } | null>(null);
  const [showLatencyDetail, setShowLatencyDetail] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Execute debounced search when inputs change
  useEffect(() => {
    if (!isOpen || !query.trim()) {
      setResponse(null);
      setLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const req: SearchRequest = {
          query: query.trim(),
          mode,
          top_k: 10,
          folder_id: selectedFolder || undefined,
          extension: selectedExt || undefined,
        };
        const data = await searchEvidence(req);
        setResponse(data);
      } catch (err: any) {
        setError(err.message || "Failed to execute search");
      } finally {
        setLoading(false);
      }
    }, 180);

    return () => clearTimeout(timer);
  }, [query, mode, selectedFolder, selectedExt, isOpen]);

  // Handle keyboard navigation (Escape to close)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleAction = async (
    chunkId: string,
    action: "OPEN_FILE" | "OPEN_FOLDER" | "COPY_PATH",
    path: string
  ) => {
    try {
      const res = await executeSafeAction(action, path);
      if (action === "COPY_PATH") {
        await navigator.clipboard.writeText(path);
        setActionFeedback({ id: chunkId, msg: "Path copied!" });
      } else {
        setActionFeedback({ id: chunkId, msg: res.message });
      }
      setTimeout(() => setActionFeedback(null), 2500);
    } catch (err: any) {
      setActionFeedback({ id: chunkId, msg: `Error: ${err.message}` });
      setTimeout(() => setActionFeedback(null), 3000);
    }
  };

  if (!isOpen) return null;

  const exampleQueries = [
    "Cryptographic hashing with streaming SHA-256 validation",
    "Write-Ahead Logging (WAL) mode enabled",
    "def get_config():",
    "quarterly business revenue and financial profit margins",
    "zero orphan worker processes",
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 bg-slate-950/70 backdrop-blur-sm animate-fade-in p-4">
      <div
        className="w-full max-w-3xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="p-4 border-b border-slate-800 bg-slate-900/90 flex items-center gap-3">
          <svg
            className="w-6 h-6 text-indigo-400 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search documents, code, tables, headings across local vault..."
            className="w-full bg-transparent text-slate-100 text-lg placeholder-slate-500 focus:outline-none"
          />
          {loading && (
            <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin shrink-0" />
          )}
          {query && (
            <button
              onClick={() => setQuery("")}
              className="text-slate-400 hover:text-slate-200 text-sm px-2 py-1 bg-slate-800 rounded"
            >
              Clear
            </button>
          )}
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 border border-slate-700 rounded bg-slate-800/50"
            title="Press Esc to close"
          >
            ESC
          </button>
        </div>

        {/* Filter Controls Bar */}
        <div className="px-4 py-2 bg-slate-950/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
          {/* Retrieval Mode Radio */}
          <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800">
            <button
              onClick={() => setMode("hybrid")}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                mode === "hybrid"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Hybrid (RRF)
            </button>
            <button
              onClick={() => setMode("bm25")}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                mode === "bm25"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Lexical (BM25)
            </button>
            <button
              onClick={() => setMode("dense")}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                mode === "dense"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Dense (Semantic)
            </button>
          </div>

          {/* Metadata Filters */}
          <div className="flex items-center gap-2">
            {folders.length > 0 && (
              <select
                value={selectedFolder}
                onChange={(e) => setSelectedFolder(e.target.value)}
                className="bg-slate-900 border border-slate-800 text-slate-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
              >
                <option value="">All Folders</option>
                {folders.map((f) => (
                  <option key={f.folder_id} value={f.folder_id}>
                    {f.path.split(/[\\/]/).pop() || f.path}
                  </option>
                ))}
              </select>
            )}

            <select
              value={selectedExt}
              onChange={(e) => setSelectedExt(e.target.value)}
              className="bg-slate-900 border border-slate-800 text-slate-300 rounded px-2 py-1 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Formats</option>
              <option value=".pdf">PDF (.pdf)</option>
              <option value=".docx">Word (.docx)</option>
              <option value=".pptx">PowerPoint (.pptx)</option>
              <option value=".xlsx">Excel (.xlsx)</option>
              <option value=".csv">CSV (.csv)</option>
              <option value=".md">Markdown (.md)</option>
              <option value=".py">Python (.py)</option>
              <option value=".json">JSON (.json)</option>
            </select>
          </div>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {error && (
            <div className="p-3 bg-red-950/50 border border-red-800 text-red-300 rounded-lg text-sm">
              {error}
            </div>
          )}

          {!query.trim() && (
            <div className="py-8 text-center space-y-4">
              <p className="text-slate-400 text-sm">
                Type a query to search with deterministic local retrieval.
              </p>
              <div className="flex flex-wrap justify-center gap-2 max-w-lg mx-auto">
                {exampleQueries.map((ex, i) => (
                  <button
                    key={i}
                    onClick={() => setQuery(ex)}
                    className="text-xs px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-indigo-300 rounded-full border border-slate-700 transition"
                  >
                    "{ex}"
                  </button>
                ))}
              </div>
            </div>
          )}

          {response && (
            <>
              {/* Header metrics */}
              <div className="flex items-center justify-between text-xs text-slate-400 pb-1 border-b border-slate-800/60">
                <span>
                  Found <strong className="text-slate-200">{response.total_found}</strong> evidence candidates
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono bg-slate-800 px-2 py-0.5 rounded text-indigo-300">
                    {response.latency_breakdown_ms.total_request} ms
                  </span>
                  <button
                    onClick={() => setShowLatencyDetail(!showLatencyDetail)}
                    className="text-slate-400 hover:text-slate-200 underline text-[11px]"
                  >
                    {showLatencyDetail ? "Hide breakdown" : "Timing breakdown"}
                  </button>
                </div>
              </div>

              {/* Latency Breakdown Panel */}
              {showLatencyDetail && (
                <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800 grid grid-cols-3 sm:grid-cols-6 gap-2 text-center text-xs font-mono">
                  <div className="bg-slate-900/80 p-1.5 rounded">
                    <div className="text-slate-500 text-[10px]">Norm</div>
                    <div className="text-slate-200 font-semibold">{response.latency_breakdown_ms.normalization} ms</div>
                  </div>
                  <div className="bg-slate-900/80 p-1.5 rounded">
                    <div className="text-slate-500 text-[10px]">Lexical FTS5</div>
                    <div className="text-slate-200 font-semibold">{response.latency_breakdown_ms.lexical_search} ms</div>
                  </div>
                  <div className="bg-slate-900/80 p-1.5 rounded">
                    <div className="text-slate-500 text-[10px]">Query Embed</div>
                    <div className="text-slate-200 font-semibold">{response.latency_breakdown_ms.query_embedding} ms</div>
                  </div>
                  <div className="bg-slate-900/80 p-1.5 rounded">
                    <div className="text-slate-500 text-[10px]">Vector Vec0</div>
                    <div className="text-slate-200 font-semibold">{response.latency_breakdown_ms.dense_search} ms</div>
                  </div>
                  <div className="bg-slate-900/80 p-1.5 rounded">
                    <div className="text-slate-500 text-[10px]">RRF Fusion</div>
                    <div className="text-slate-200 font-semibold">{response.latency_breakdown_ms.rrf_fusion} ms</div>
                  </div>
                  <div className="bg-indigo-950/60 border border-indigo-800/50 p-1.5 rounded">
                    <div className="text-indigo-300 text-[10px]">Total Req</div>
                    <div className="text-indigo-200 font-semibold">{response.latency_breakdown_ms.total_request} ms</div>
                  </div>
                </div>
              )}

              {response.results.length === 0 && (
                <div className="py-8 text-center text-slate-500 text-sm">
                  No matching chunks found. Try broader keywords or change retrieval mode.
                </div>
              )}

              {/* Candidates List */}
              {response.results.map((r) => (
                <div
                  key={r.chunk_id}
                  className="p-3.5 bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/60 rounded-lg transition space-y-2 group"
                >
                  {/* Top line: Rank, File, Badges */}
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-400 font-mono">#{r.rank}</span>
                      <span className="font-semibold text-slate-100">{r.source_file}</span>
                      <span className="text-slate-500 font-mono text-[11px] bg-slate-900 px-1.5 py-0.5 rounded">
                        {r.source_file.split(".").pop()?.toUpperCase()}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 font-mono text-[11px]">
                      {r.rrf_score !== null && r.rrf_score !== undefined && (
                        <span className="text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/40">
                          RRF: {r.rrf_score.toFixed(4)}
                        </span>
                      )}
                      {r.dense_score !== null && r.dense_score !== undefined ? (
                        <span className="text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/40" title={`Dense Rank: #${r.dense_rank || '—'}`}>
                          Dense: {r.dense_score.toFixed(3)}
                        </span>
                      ) : (
                        <span className="text-slate-500 bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800/40" title="Not in dense candidate pool">
                          Dense: —
                        </span>
                      )}
                      {r.lexical_score !== null && r.lexical_score !== undefined ? (
                        <span className="text-amber-400 bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-800/40" title={`BM25 Rank: #${r.lexical_rank || '—'}`}>
                          BM25: {r.lexical_score.toFixed(1)}
                        </span>
                      ) : (
                        <span className="text-slate-500 bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800/40" title="Not in lexical candidate pool">
                          BM25: —
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Breadcrumbs: H1 > H2 > Page */}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {r.h1_parent && (
                      <span className="bg-slate-900/90 text-indigo-300 px-1.5 py-0.5 rounded font-medium">
                        {r.h1_parent}
                      </span>
                    )}
                    {r.h2_parent && (
                      <span className="text-slate-400 flex items-center gap-1">
                        <span>›</span>
                        <span className="text-slate-300">{r.h2_parent}</span>
                      </span>
                    )}
                    {r.page && (
                      <span className="text-slate-500 text-[11px]">Page {r.page}</span>
                    )}
                    {r.line_start && r.line_end && (
                      <span className="text-slate-500 text-[11px]">Lines {r.line_start}–{r.line_end}</span>
                    )}
                    <span className="text-slate-600 font-mono text-[10px] ml-auto">
                      ID: {r.chunk_id}
                    </span>
                  </div>

                  {/* Authentic Snippet */}
                  <p className="text-sm text-slate-200 leading-relaxed font-sans bg-slate-900/60 p-2.5 rounded border border-slate-800/60">
                    {r.snippet}
                  </p>

                  {/* Actions & Feedback */}
                  <div className="flex items-center justify-between pt-1 text-xs">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleAction(r.chunk_id, "OPEN_FILE", r.source_path)}
                        className="text-slate-400 hover:text-indigo-300 font-medium transition"
                      >
                        Open File
                      </button>
                      <span className="text-slate-600">•</span>
                      <button
                        onClick={() => handleAction(r.chunk_id, "OPEN_FOLDER", r.source_path)}
                        className="text-slate-400 hover:text-indigo-300 font-medium transition"
                      >
                        Open Folder
                      </button>
                      <span className="text-slate-600">•</span>
                      <button
                        onClick={() => handleAction(r.chunk_id, "COPY_PATH", r.source_path)}
                        className="text-slate-400 hover:text-indigo-300 font-medium transition"
                      >
                        Copy Path
                      </button>
                      {onInspectChunk && (
                        <>
                          <span className="text-slate-600">•</span>
                          <button
                            onClick={() => {
                              onInspectChunk(r.chunk_id);
                              onClose();
                            }}
                            className="text-indigo-400 hover:text-indigo-200 font-medium transition"
                          >
                            Inspect Chunk
                          </button>
                        </>
                      )}
                    </div>

                    {actionFeedback?.id === r.chunk_id && (
                      <span className="text-emerald-400 font-medium animate-pulse">
                        {actionFeedback.msg}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2.5 bg-slate-950 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded font-mono text-[10px]">
                Ctrl
              </kbd>{" "}
              +{" "}
              <kbd className="px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded font-mono text-[10px]">
                K
              </kbd>{" "}
              to open
            </span>
            <span>•</span>
            <span>
              <kbd className="px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded font-mono text-[10px]">
                ESC
              </kbd>{" "}
              to close
            </span>
          </div>
          <span className="font-mono text-[11px] text-slate-400">
            No LLM • 100% Deterministic Local Search
          </span>
        </div>
      </div>
    </div>
  );
};
