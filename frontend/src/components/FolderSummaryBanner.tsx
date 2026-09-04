import { useEffect, useState } from "react";
import { FolderInsight, Folder } from "../types";
import { fetchFolderInsight, generateFolderInsight } from "../services/api";

export function FolderSummaryBanner({ folders }: { folders: Folder[] }) {
  const [folderId, setFolderId] = useState("");
  const [insight, setInsight] = useState<FolderInsight | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!folderId && folders[0]) {
      setFolderId(folders[0].folder_id);
    }
  }, [folders, folderId]);

  useEffect(() => {
    if (!folderId) return;
    const controller = new AbortController();
    let mounted = true;

    setError(null);
    fetchFolderInsight(folderId, controller.signal)
      .then((res) => {
        if (mounted) setInsight(res);
      })
      .catch((e) => {
        if (!mounted || (e instanceof Error && e.name === "AbortError")) return;
        setError(e instanceof Error ? e.message : "Unable to load folder summary");
      });

    return () => {
      mounted = false;
      controller.abort();
    };
  }, [folderId]);

  const generate = async () => {
    if (!folderId || generating) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await generateFolderInsight(folderId);
      setInsight(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Local generation failed");
    } finally {
      setGenerating(false);
    }
  };

  if (!folders.length) return null;

  return (
    <section className="rounded-xl border border-indigo-800/50 bg-indigo-950/20 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-3">
        <b className="text-indigo-200">Folder summary</b>
        <select
          value={folderId}
          onChange={(e) => setFolderId(e.target.value)}
          className="bg-dark-900 border border-dark-600 rounded px-2 py-1 text-slate-200"
        >
          {folders.map((f) => (
            <option key={f.folder_id} value={f.folder_id}>
              {f.path}
            </option>
          ))}
        </select>
        <span className="text-slate-400">{generating ? "Generating locally…" : insight?.status || "Loading…"}</span>
        {insight &&
          ["NOT_GENERATED", "STALE", "FAILED", "MODEL_UNAVAILABLE"].includes(insight.status) && (
            <button
              disabled={generating}
              onClick={generate}
              className="rounded bg-indigo-700 hover:bg-indigo-600 px-2 py-1 text-white disabled:opacity-50 transition"
            >
              {generating ? "Generating…" : "Generate locally"}
            </button>
          )}
      </div>
      {error ? (
        <p className="mt-2 text-rose-300">{error}</p>
      ) : (
        insight && (
          <>
            <p className="mt-2 text-slate-200">
              {insight.executive_summary ||
                `Contains ${insight.structural_summary.total_files} tracked files and ${insight.structural_summary.total_chunks} indexed chunks.`}
            </p>
            {insight.key_themes.length > 0 && (
              <p className="mt-1 text-slate-400">Themes: {insight.key_themes.join(" · ")}</p>
            )}
          </>
        )
      )}
    </section>
  );
}
