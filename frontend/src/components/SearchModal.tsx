import React, { useState, useEffect, useRef, useMemo } from "react";
import { SearchRequest, SearchResponse, Folder, SearchResultItem } from "../types";
import { searchEvidence, executeSafeAction } from "../services/api";

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  folders: Folder[];
  onInspectChunk?: (fileId: string, filename: string, chunkId: string) => void;
}

interface FileResultGroup {
  fileKey: string;
  file_id: string;
  source_file: string;
  source_path: string;
  bestRank: number;
  bestScore: number;
  chunks: SearchResultItem[];
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  folders,
  onInspectChunk,
}) => {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"hybrid" | "bm25" | "dense">("hybrid");
  const [quality, setQuality] = useState<"fast" | "quality">("fast");
  const [selectedFolder, setSelectedFolder] = useState<string>("");
  const [selectedExt, setSelectedExt] = useState<string>("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; msg: string } | null>(null);
  const [showLatencyDetail, setShowLatencyDetail] = useState(false);
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});

  const groupedResults = useMemo<FileResultGroup[]>(() => {
    if (!response?.results) return [];
    const groups: FileResultGroup[] = [];
    const map = new Map<string, FileResultGroup>();

    for (const r of response.results) {
      const key = r.file_id || r.source_path || r.source_file;
      let g = map.get(key);
      if (!g) {
        g = {
          fileKey: key,
          file_id: r.file_id,
          source_file: r.source_file,
          source_path: r.source_path,
          bestRank: r.rank,
          bestScore: r.score,
          chunks: [],
        };
        map.set(key, g);
        groups.push(g);
      }
      g.chunks.push(r);
    }
    return groups;
  }, [response?.results]);

  const inputRef = useRef<HTMLInputElement>(null);
  // Tracks the AbortController for the most recently *sent* search request,
  // so that an in-flight request can be cancelled when a newer one supersedes
  // it (e.g. the user keeps typing before the previous request resolves).
  const abortControllerRef = useRef<AbortController | null>(null);
  // Monotonically increasing counter identifying the most recently *sent*
  // request. Used as a belt-and-suspenders guard against stale responses
  // clobbering newer ones, in case a response resolves before its abort
  // signal is observed (e.g. it was already in-flight past the point where
  // fetch() honors cancellation).
  const requestSeqRef = useRef(0);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // If mode is switched away from hybrid, clamp quality to fast
  const handleModeChange = (newMode: "hybrid" | "bm25" | "dense") => {
    setMode(newMode);
    if (newMode !== "hybrid") {
      setQuality("fast");
    }
  };

  // Execute debounced search when inputs change
  useEffect(() => {
    if (!isOpen || !query.trim()) {
      // A new empty/closed state supersedes any in-flight request too.
      abortControllerRef.current?.abort();
      setResponse(null);
      setLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      // Cancel any previous request that might still be in flight before
      // starting a new one, and record a sequence id for this request so
      // that even a response which resolves despite cancellation (or races
      // past the abort signal) can be detected as stale and ignored.
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const seq = ++requestSeqRef.current;

      setLoading(true);
      setError(null);
      try {
        const req: SearchRequest = {
          query: query.trim(),
          mode,
          quality: mode === "hybrid" ? quality : "fast",
          top_k: 10,
          folder_id: selectedFolder || undefined,
          extension: selectedExt || undefined,
        };
        const data = await searchEvidence(req, controller.signal);
        // Ignore this response if a newer request has since been issued or
        // this request was aborted (superseded) while in flight.
        if (seq !== requestSeqRef.current || controller.signal.aborted) {
          return;
        }
        setResponse(data);
      } catch (err: any) {
        // A deliberate abort (superseded request) should not surface as a
        // user-facing error; only report genuine failures for the latest
        // request.
        const isAbort = err?.name === "AbortError";
        if (isAbort || seq !== requestSeqRef.current) {
          return;
        }
        setError(err.message || "Failed to execute search");
      } finally {
        if (seq === requestSeqRef.current) {
          setLoading(false);
        }
      }
    }, 180);

    return () => {
      clearTimeout(timer);
      abortControllerRef.current?.abort();
    };
  }, [query, mode, quality, selectedFolder, selectedExt, isOpen]);


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
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 bg-slate-950/70 backdrop-blur-sm animate-fade-in p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search Modal"
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
            aria-label="Search query"
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
              aria-label="Clear search query"
              className="text-slate-400 hover:text-slate-200 text-sm px-2 py-1 bg-slate-800 rounded"
            >
              Clear
            </button>
          )}
          <button
            onClick={onClose}
            aria-label="Close search modal"
            className="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 border border-slate-700 rounded bg-slate-800/50"
            title="Press Esc to close"
          >
            ESC
          </button>
        </div>

        {/* Filter Controls Bar */}
        <div className="px-4 py-2 bg-slate-950/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            {/* Retrieval Mode Radio */}
            <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800" role="radiogroup" aria-label="Retrieval mode">
              <button
                onClick={() => handleModeChange("hybrid")}
                aria-label="Hybrid RRF retrieval mode"
                className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                  mode === "hybrid"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Hybrid (RRF)
              </button>
              <button
                onClick={() => handleModeChange("bm25")}
                aria-label="Lexical BM25 retrieval mode"
                className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                  mode === "bm25"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Lexical (BM25)
              </button>
              <button
                onClick={() => handleModeChange("dense")}
                aria-label="Dense semantic retrieval mode"
                className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                  mode === "dense"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Dense (Semantic)
              </button>
            </div>

            {/* Quality Selector */}
            <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800" role="radiogroup" aria-label="Pipeline quality">
              <button
                onClick={() => setQuality("fast")}
                aria-label="Fast retrieval quality"
                className={`px-2 py-1 rounded-md font-medium transition-colors ${
                  quality === "fast"
                    ? "bg-slate-700 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
                title="Fast Mode: Low-latency direct retrieval without cross-encoder inference"
              >
                Fast
              </button>
              <button
                onClick={() => mode === "hybrid" && setQuality("quality")}
                disabled={mode !== "hybrid"}
                aria-label="Quality reranked retrieval"
                className={`px-2 py-1 rounded-md font-medium transition-colors ${
                  quality === "quality" && mode === "hybrid"
                    ? "bg-purple-600 text-white shadow-sm"
                    : mode !== "hybrid"
                    ? "text-slate-600 cursor-not-allowed"
                    : "text-slate-400 hover:text-slate-200"
                }`}
                title={
                  mode === "hybrid"
                    ? "Quality Mode: Hybrid RRF + Cross-Encoder reranking for highest precision"
                    : "Quality mode requires Hybrid retrieval"
                }
              >
                Quality
              </button>
            </div>
          </div>

          {/* Metadata Filters */}
          <div className="flex items-center gap-2">
            {Array.isArray(folders) && folders.length > 0 && (
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

          {response?.degraded && (
            <div className="p-2.5 bg-amber-950/40 border border-amber-700/60 rounded-lg text-xs text-amber-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-semibold uppercase tracking-wider text-[10px] bg-amber-800/60 px-1.5 py-0.5 rounded">
                  Degraded Search
                </span>
                <span>
                  {response.degraded_reason || "Subsystem unavailable; degraded fallback active."}
                </span>
              </div>
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
                  Found <strong className="text-slate-200">{response.total_found}</strong> evidence candidates across{" "}
                  <strong className="text-slate-200">{groupedResults.length}</strong> {groupedResults.length === 1 ? "file" : "files"}
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
                <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800 grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-2 text-center text-xs font-mono">
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
                  {typeof response.latency_breakdown_ms.reranker_inference === "number" && (
                    <div className="bg-purple-950/60 border border-purple-800/50 p-1.5 rounded">
                      <div className="text-purple-300 text-[10px]">Reranker</div>
                      <div className="text-purple-200 font-semibold">{response.latency_breakdown_ms.reranker_inference} ms</div>
                    </div>
                  )}
                  <div className="bg-indigo-950/60 border border-indigo-800/50 p-1.5 rounded">
                    <div className="text-indigo-300 text-[10px]">Total Req</div>
                    <div className="text-indigo-200 font-semibold">{response.latency_breakdown_ms.total_request} ms</div>
                  </div>
                </div>
              )}

              {response.results.length === 0 && (
                <div className="py-8 text-center text-slate-500 text-sm space-y-1">
                  <div className="font-medium text-slate-400">
                    {response.explicit_filename_intent
                      ? "File not found or not indexed"
                      : "No matching chunks found"}
                  </div>
                  <div className="text-xs text-slate-500">
                    {response.explicit_filename_intent
                      ? `No indexed file matching "${response.explicit_filename_intent}" exists in the current corpus.`
                      : "Try broader keywords or change retrieval mode."}
                  </div>
                </div>
              )}

              {/* Grouped Candidates List */}
              {groupedResults.map((group) => {
                const primaryChunk = group.chunks[0];
                const additionalChunks = group.chunks.slice(1);
                const isExpanded = !!expandedFiles[group.fileKey];

                return (
                  <div
                    key={group.fileKey}
                    className="p-3.5 bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/60 rounded-lg transition space-y-2.5 group"
                  >
                    {/* Top line: File Rank, File Name, Badges, Multi-Chunk Pill */}
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-400 font-mono">#{group.bestRank}</span>
                        <span className="font-semibold text-slate-100 text-sm">{group.source_file}</span>
                        <span className="text-slate-500 font-mono text-[11px] bg-slate-900 px-1.5 py-0.5 rounded">
                          {group.source_file.split(".").pop()?.toUpperCase()}
                        </span>
                        {group.chunks.length > 1 && (
                          <span className="text-indigo-300 bg-indigo-950/80 border border-indigo-800/50 text-[11px] px-2 py-0.5 rounded-full font-medium">
                            {group.chunks.length} relevant chunks found
                          </span>
                        )}
                      </div>

                      {/* Score metrics for the top chunk */}
                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        {primaryChunk.reranker_score !== null && primaryChunk.reranker_score !== undefined && (
                          <span className="text-purple-400 bg-purple-950/60 px-1.5 py-0.5 rounded border border-purple-800/40" title="Cross-Encoder Relevance Score">
                            Rerank: {primaryChunk.reranker_score.toFixed(3)}
                          </span>
                        )}
                        {primaryChunk.rrf_score !== null && primaryChunk.rrf_score !== undefined && (
                          <span className="text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/40">
                            RRF: {primaryChunk.rrf_score.toFixed(4)}
                          </span>
                        )}
                        {primaryChunk.dense_score !== null && primaryChunk.dense_score !== undefined ? (
                          <span className="text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/40" title={`Dense Rank: #${primaryChunk.dense_rank || '—'}`}>
                            Dense: {primaryChunk.dense_score.toFixed(3)}
                          </span>
                        ) : (
                          <span className="text-slate-500 bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800/40" title="Not in dense candidate pool">
                            Dense: —
                          </span>
                        )}
                        {primaryChunk.lexical_score !== null && primaryChunk.lexical_score !== undefined ? (
                          <span className="text-amber-400 bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-800/40" title={`BM25 Rank: #${primaryChunk.lexical_rank || '—'}`}>
                            BM25: {primaryChunk.lexical_score.toFixed(1)}
                          </span>
                        ) : (
                          <span className="text-slate-500 bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800/40" title="Not in lexical candidate pool">
                            BM25: —
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Primary Evidence Chunk */}
                    <div className="space-y-1.5 pl-2 border-l-2 border-indigo-500/40">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-400 bg-indigo-950/60 px-1.5 py-0.5 rounded">
                          Top Match
                        </span>
                        {primaryChunk.h1_parent && (
                          <span className="bg-slate-900/90 text-indigo-300 px-1.5 py-0.5 rounded font-medium">
                            {primaryChunk.h1_parent}
                          </span>
                        )}
                        {primaryChunk.h2_parent && (
                          <span className="text-slate-400 flex items-center gap-1">
                            <span>›</span>
                            <span className="text-slate-300">{primaryChunk.h2_parent}</span>
                          </span>
                        )}
                        {primaryChunk.page && (
                          <span className="text-slate-500 text-[11px]">Page {primaryChunk.page}</span>
                        )}
                        {primaryChunk.line_start && primaryChunk.line_end && (
                          <span className="text-slate-500 text-[11px]">Lines {primaryChunk.line_start}–{primaryChunk.line_end}</span>
                        )}
                        <span className="text-slate-600 font-mono text-[10px] ml-auto">
                          ID: {primaryChunk.chunk_id}
                        </span>
                      </div>

                      {/* Authentic Snippet */}
                      <p className="text-sm text-slate-200 leading-relaxed font-sans bg-slate-900/60 p-2.5 rounded border border-slate-800/60">
                        {primaryChunk.snippet}
                      </p>
                    </div>

                    {/* Additional Chunks Drawer if multiple chunks match */}
                    {additionalChunks.length > 0 && (
                      <div className="pt-1">
                        <button
                          onClick={() =>
                            setExpandedFiles((prev) => ({ ...prev, [group.fileKey]: !prev[group.fileKey] }))
                          }
                          className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 font-medium py-1 px-2.5 rounded bg-indigo-950/40 hover:bg-indigo-950/70 border border-indigo-900/40 transition cursor-pointer"
                        >
                          <span>{isExpanded ? "▲ Hide additional chunks" : `▼ View ${additionalChunks.length} more matching ${additionalChunks.length === 1 ? "chunk" : "chunks"} in this file`}</span>
                        </button>

                        {isExpanded && (
                          <div className="mt-2.5 space-y-2 pl-3 border-l-2 border-slate-700/60">
                            {additionalChunks.map((c) => (
                              <div
                                key={c.chunk_id}
                                className="p-2.5 bg-slate-900/70 rounded border border-slate-800/80 space-y-1.5"
                              >
                                <div className="flex items-center justify-between text-xs text-slate-400">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="font-mono text-slate-400 font-bold">#{c.rank}</span>
                                    {c.h1_parent && (
                                      <span className="bg-slate-800 text-indigo-300 px-1.5 py-0.5 rounded text-[11px]">
                                        {c.h1_parent}
                                      </span>
                                    )}
                                    {c.h2_parent && (
                                      <span className="text-slate-400 text-[11px]">› {c.h2_parent}</span>
                                    )}
                                    {c.page && <span className="text-[11px] text-slate-500">Page {c.page}</span>}
                                    {c.line_start && c.line_end && (
                                      <span className="text-[11px] text-slate-500">
                                        Lines {c.line_start}–{c.line_end}
                                      </span>
                                    )}
                                  </div>

                                  <div className="flex items-center gap-2">
                                    {onInspectChunk && (
                                      <button
                                        onClick={() => {
                                          onInspectChunk(c.file_id, c.source_file, c.chunk_id);
                                          onClose();
                                        }}
                                        className="text-indigo-400 hover:text-indigo-200 text-xs font-medium cursor-pointer"
                                      >
                                        Inspect Chunk
                                      </button>
                                    )}
                                    <span className="text-slate-600 font-mono text-[10px]">ID: {c.chunk_id}</span>
                                  </div>
                                </div>

                                <p className="text-xs text-slate-300 leading-relaxed font-sans bg-slate-950/50 p-2 rounded">
                                  {c.snippet}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* File & Primary Chunk Actions */}
                    <div className="flex items-center justify-between pt-1 text-xs">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleAction(primaryChunk.chunk_id, "OPEN_FILE", group.source_path)}
                          className="text-slate-400 hover:text-indigo-300 font-medium transition cursor-pointer"
                        >
                          Open File
                        </button>
                        <span className="text-slate-600">•</span>
                        <button
                          onClick={() => handleAction(primaryChunk.chunk_id, "OPEN_FOLDER", group.source_path)}
                          className="text-slate-400 hover:text-indigo-300 font-medium transition cursor-pointer"
                        >
                          Open Folder
                        </button>
                        <span className="text-slate-600">•</span>
                        <button
                          onClick={() => handleAction(primaryChunk.chunk_id, "COPY_PATH", group.source_path)}
                          className="text-slate-400 hover:text-indigo-300 font-medium transition cursor-pointer"
                        >
                          Copy Path
                        </button>
                        {onInspectChunk && (
                          <>
                            <span className="text-slate-600">•</span>
                            <button
                              onClick={() => {
                                onInspectChunk(primaryChunk.file_id, primaryChunk.source_file, primaryChunk.chunk_id);
                                onClose();
                              }}
                              className="text-indigo-400 hover:text-indigo-200 font-medium transition cursor-pointer"
                            >
                              Inspect Chunk
                            </button>
                          </>
                        )}
                      </div>

                      {actionFeedback && actionFeedback.id === primaryChunk.chunk_id && (
                        <span className="text-emerald-400 font-medium animate-pulse">
                          {actionFeedback.msg}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
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
            100% Local Deterministic Search • Fast & Quality Modes
          </span>
        </div>
      </div>
    </div>
  );
};

