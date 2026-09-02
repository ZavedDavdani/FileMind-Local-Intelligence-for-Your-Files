import { useEffect, useState } from "react";
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
  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [i, r, c] = await Promise.all([fetchDocumentInsight(fileId), fetchRelatedFiles(fileId), fetchKnowledgeConnections(fileId)]);
      setInsight(i); setRelated(r); setConnections(c);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load local knowledge"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [fileId]);
  const generate = async () => { setGenerating(true); try { setInsight(await generateDocumentInsight(fileId)); } catch (e) { setError(e instanceof Error ? e.message : "Generation failed"); } finally { setGenerating(false); } };
  const inspect = (citation: { file_id: string; source_file: string; chunk_id: string }) => onInspectChunk(citation.file_id, citation.source_file, citation.chunk_id);
  return <div className="fixed inset-0 z-50 bg-black/60 flex justify-end" role="dialog" aria-modal="true" aria-label={`Knowledge details for ${filename}`}>
    <section className="w-full max-w-2xl h-full overflow-y-auto bg-dark-900 border-l border-dark-600 p-5 text-sm">
      <header className="flex justify-between gap-3 border-b border-dark-700 pb-3"><div><h2 className="text-lg font-semibold text-white">{filename}</h2><p className="text-xs text-slate-400">Local, source-backed Second Brain details</p></div><button onClick={onClose} aria-label="Close knowledge details"><X /></button></header>
      {loading && <p className="py-6 text-slate-400">Loading local knowledge…</p>}
      {error && <p className="my-4 rounded bg-rose-950/40 p-3 text-rose-200">{error}</p>}
      {insight && <section className="mt-5 space-y-3"><div className="flex items-center justify-between"><h3 className="font-semibold text-indigo-300"><Sparkles className="mr-1 inline w-4" />Document Insight</h3><span className="text-xs text-slate-400">{insight.status}</span></div>
        {(insight.status === "NOT_GENERATED" || insight.status === "STALE" || insight.status === "FAILED" || insight.status === "MODEL_UNAVAILABLE") && <button disabled={generating} onClick={generate} className="rounded bg-indigo-700 px-3 py-1.5 text-xs disabled:opacity-50">{generating ? "Generating locally…" : "Generate locally"}</button>}
        {insight.executive_summary ? <p className="whitespace-pre-wrap text-slate-200">{insight.executive_summary}</p> : <p className="text-slate-400">No generated insight is available. Source files remain authoritative.</p>}
        {!!insight.key_topics.length && <p className="text-xs text-slate-300">Topics: {insight.key_topics.join(" · ")}</p>}
        {!!insight.key_decisions.length && <p className="text-xs text-slate-300">Decisions: {insight.key_decisions.join(" · ")}</p>}
        {!!insight.citations.length && <div className="flex flex-wrap gap-2">{insight.citations.map(c => <button key={c.citation_id} onClick={() => inspect(c)} className="rounded border border-cyan-700 px-2 py-1 text-xs text-cyan-300">[{c.citation_id}] {c.source_file}</button>)}</div>}
      </section>}
      {related && <section className="mt-6"><h3 className="font-semibold text-indigo-300"><Files className="mr-1 inline w-4" />Related Files</h3>{related.results.length ? <ul className="mt-2 space-y-2">{related.results.map(r => <li key={r.file_id} className="rounded border border-dark-600 p-2"><b>{r.filename}</b><p className="text-xs text-slate-400">{r.explanation}</p><button onClick={() => onInspectChunk(r.file_id, r.filename, r.primary_matched_chunk.chunk_id)} className="text-xs text-cyan-300">Inspect supporting evidence</button></li>)}</ul> : <p className="mt-2 text-xs text-slate-400">No related indexed files.</p>}</section>}
      {connections && <section className="mt-6"><h3 className="font-semibold text-indigo-300"><Network className="mr-1 inline w-4" />Knowledge Connections</h3>{connections.connections.length ? <ul className="mt-2 space-y-2">{connections.connections.map((c, i) => <li key={`${c.connection_type}-${c.target_file.file_id}-${i}`} className="rounded border border-dark-600 p-2"><b>{c.target_file.filename}</b><p className="text-xs text-slate-400">{c.explanation}</p>{c.source_evidence[0] && <button onClick={() => inspect(c.source_evidence[0])} className="text-xs text-cyan-300">Inspect source evidence</button>}</li>)}</ul> : <p className="mt-2 text-xs text-slate-400">No current source-backed connections.</p>}</section>}
    </section></div>;
}
