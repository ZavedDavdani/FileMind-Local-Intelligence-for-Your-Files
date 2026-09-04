import { useEffect, useState, useRef } from "react";
import { X, Sparkles, Network, Files } from "lucide-react";
import { DocumentInsight, KnowledgeConnectionsResponse, RelatedFilesResponse } from "../types";
import { fetchDocumentInsight, fetchKnowledgeConnections, fetchRelatedFiles, generateDocumentInsight } from "../services/api";

export function SecondBrainSheet({ fileId, filename, onClose, onInspectChunk }: {
  fileId: string; filename: string; onClose: () => void;
  onInspectChunk: (fileId: string, filename: string, chunkId: string) => void;
}) {
  const [insight, setInsight] = useState<DocumentInsight | null>(null);
  const [related, setRelated] = useState<RelatedFilesResponse | null>(null);
  const [connections, setConnections] = useState<KnowledgeConnectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let mounted = true;

    setLoading(true);
    setError(null);

    Promise.all([
      fetchDocumentInsight(fileId, controller.signal),
      fetchRelatedFiles(fileId, 5, "fast", controller.signal),
      fetchKnowledgeConnections(fileId, controller.signal),
    ])
      .then(([i, r, c]) => {
        if (!mounted) return;
        setInsight(i);
        setRelated(r);
        setConnections(c);
      })
      .catch((e) => {
        if (!mounted || (e instanceof Error && e.name === "AbortError")) return;
        setError(e instanceof Error ? e.message : "Unable to load local knowledge");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
      controller.abort();
    };
  }, [fileId]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await generateDocumentInsight(fileId);
      setInsight(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const inspect = (citation: { file_id: string; source_file: string; chunk_id: string }) =>
    onInspectChunk(citation.file_id, citation.source_file, citation.chunk_id);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex justify-end animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label={`Knowledge details for ${filename}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section className="w-full max-w-2xl h-full overflow-y-auto bg-dark-900 border-l border-dark-600 p-5 text-sm">
        <header className="flex justify-between gap-3 border-b border-dark-700 pb-3">
          <div>
            <h2 className="text-lg font-semibold text-white">{filename}</h2>
            <p className="text-xs text-slate-400">Local, source-backed Second Brain details</p>
          </div>
          <button onClick={onClose} aria-label="Close knowledge details" className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </header>

        {loading && <p className="py-6 text-slate-400">Loading local knowledge…</p>}
        {error && <p className="my-4 rounded bg-rose-950/40 p-3 text-rose-200">{error}</p>}

        {insight && (
          <section className="mt-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-indigo-300 flex items-center">
                <Sparkles className="mr-1.5 inline w-4 h-4" />
                Document Insight
              </h3>
              <span className="text-xs text-slate-400">{insight.status}</span>
            </div>
            {(insight.status === "NOT_GENERATED" ||
              insight.status === "STALE" ||
              insight.status === "FAILED" ||
              insight.status === "MODEL_UNAVAILABLE") && (
              <button
                disabled={generating}
                onClick={generate}
                className="rounded bg-indigo-700 hover:bg-indigo-600 px-3 py-1.5 text-xs text-white disabled:opacity-50 transition"
              >
                {generating ? "Generating locally…" : "Generate locally"}
              </button>
            )}
            {insight.executive_summary ? (
              <p className="whitespace-pre-wrap text-slate-200">{insight.executive_summary}</p>
            ) : (
              <p className="text-slate-400">No generated insight is available. Source files remain authoritative.</p>
            )}
            {!!insight.key_topics.length && (
              <p className="text-xs text-slate-300">Topics: {insight.key_topics.join(" · ")}</p>
            )}
            {!!insight.key_decisions.length && (
              <p className="text-xs text-slate-300">Decisions: {insight.key_decisions.join(" · ")}</p>
            )}
            {!!insight.citations.length && (
              <div className="flex flex-wrap gap-2 pt-1">
                {insight.citations.map((c) => (
                  <button
                    key={c.citation_id}
                    onClick={() => inspect(c)}
                    className="rounded border border-cyan-700 bg-cyan-950/40 px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-900/50 transition"
                  >
                    [{c.citation_id}] {c.source_file}
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        {related && (
          <section className="mt-6">
            <h3 className="font-semibold text-indigo-300 flex items-center">
              <Files className="mr-1.5 inline w-4 h-4" />
              Related Files
            </h3>
            {related.results.length ? (
              <ul className="mt-2 space-y-2">
                {related.results.map((r) => (
                  <li key={r.file_id} className="rounded border border-dark-600 p-3 bg-dark-800/40">
                    <b className="text-slate-100">{r.filename}</b>
                    <p className="text-xs text-slate-400 mt-0.5">{r.explanation}</p>
                    <button
                      onClick={() => onInspectChunk(r.file_id, r.filename, r.primary_matched_chunk.chunk_id)}
                      className="text-xs text-cyan-300 hover:underline mt-1.5 block"
                    >
                      Inspect supporting evidence
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-slate-400">No related indexed files.</p>
            )}
          </section>
        )}

        {connections && (
          <section className="mt-6">
            <h3 className="font-semibold text-indigo-300 flex items-center">
              <Network className="mr-1.5 inline w-4 h-4" />
              Knowledge Connections
            </h3>
            {connections.connections.length ? (
              <ul className="mt-2 space-y-2">
                {connections.connections.map((c, i) => (
                  <li key={`${c.connection_type}-${c.target_file.file_id}-${i}`} className="rounded border border-dark-600 p-3 bg-dark-800/40">
                    <b className="text-slate-100">{c.target_file.filename}</b>
                    <p className="text-xs text-slate-400 mt-0.5">{c.explanation}</p>
                    {c.source_evidence[0] && (
                      <button
                        onClick={() => inspect(c.source_evidence[0])}
                        className="text-xs text-cyan-300 hover:underline mt-1.5 block"
                      >
                        Inspect source evidence
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-slate-400">No current source-backed connections.</p>
            )}
          </section>
        )}
      </section>
    </div>
  );
}
