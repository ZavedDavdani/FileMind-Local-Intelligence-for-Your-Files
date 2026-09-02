import { useEffect, useState } from "react";
import { FolderInsight, Folder } from "../types";
import { fetchFolderInsight, generateFolderInsight } from "../services/api";

export function FolderSummaryBanner({ folders }: { folders: Folder[] }) {
  const [folderId, setFolderId] = useState("");
  const [insight, setInsight] = useState<FolderInsight | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (!folderId && folders[0]) setFolderId(folders[0].folder_id); }, [folders, folderId]);
  useEffect(() => { if (!folderId) return; setError(null); fetchFolderInsight(folderId).then(setInsight).catch(e => setError(e instanceof Error ? e.message : "Unable to load folder summary")); }, [folderId]);
  const generate = async () => { try { setInsight(await generateFolderInsight(folderId)); } catch (e) { setError(e instanceof Error ? e.message : "Local generation failed"); } };
  if (!folders.length) return null;
  return <section className="rounded-xl border border-indigo-800/50 bg-indigo-950/20 p-3 text-xs">
    <div className="flex flex-wrap items-center gap-3"><b className="text-indigo-200">Folder summary</b><select value={folderId} onChange={e => setFolderId(e.target.value)} className="bg-dark-900 border border-dark-600 rounded px-2 py-1">{folders.map(f => <option key={f.folder_id} value={f.folder_id}>{f.path}</option>)}</select><span className="text-slate-400">{insight?.status || "Loading…"}</span>
      {insight && ["NOT_GENERATED", "STALE", "FAILED", "MODEL_UNAVAILABLE"].includes(insight.status) && <button onClick={generate} className="rounded bg-indigo-700 px-2 py-1">Generate locally</button>}</div>
    {error ? <p className="mt-2 text-rose-300">{error}</p> : insight && <><p className="mt-2 text-slate-200">{insight.executive_summary || `Contains ${insight.structural_summary.total_files} tracked files and ${insight.structural_summary.total_chunks} indexed chunks.`}</p>{insight.key_themes.length > 0 && <p className="mt-1 text-slate-400">Themes: {insight.key_themes.join(" · ")}</p>}</>}
  </section>;
}
