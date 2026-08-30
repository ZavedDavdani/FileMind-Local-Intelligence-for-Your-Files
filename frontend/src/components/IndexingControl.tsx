import { IndexingStatus } from "../types";
import { Play, Pause, RefreshCw, Layers } from "lucide-react";

interface IndexingControlProps {
  status: IndexingStatus | null;
  onControl: (action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN") => void;
  disabled?: boolean;
}

export function IndexingControl({ status, onControl, disabled }: IndexingControlProps) {
  if (!status) return null;

  const { is_running, is_paused, total_files, indexed, queued, processing, failed, skipped, progress_percent } =
    status;

  return (
    <div className="bg-dark-800/60 border border-dark-700/60 rounded-2xl p-5 shadow-lg space-y-4">
      {/* Top Controls Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Layers className="w-5 h-5 text-indigo-400" />
          <div>
            <h2 className="text-sm font-semibold text-white">Filesystem Indexing Engine</h2>
            <p className="text-[11px] text-slate-400">
              {is_paused
                ? "Engine Paused"
                : processing > 0
                ? "Processing Indexing Jobs..."
                : "Idle / Up to date"}
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-2">
          {is_paused ? (
            <button
              onClick={() => onControl("RESUME")}
              disabled={disabled}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium transition-colors shadow-sm disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Resume</span>
            </button>
          ) : (
            <button
              onClick={() => onControl("PAUSE")}
              disabled={disabled || !is_running}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-amber-600/80 hover:bg-amber-500 text-white rounded-lg text-xs font-medium transition-colors shadow-sm disabled:opacity-50"
            >
              <Pause className="w-3.5 h-3.5 fill-current" />
              <span>Pause</span>
            </button>
          )}

          <button
            onClick={() => onControl("RESCAN")}
            disabled={disabled}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-slate-200 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
            title="Trigger full scan across all registered folders"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Rescan All</span>
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs font-mono">
          <span className="text-slate-400">Progress</span>
          <span className="text-indigo-300 font-semibold">{progress_percent}%</span>
        </div>
        <div className="w-full h-2 bg-dark-900 rounded-full overflow-hidden border border-dark-700">
          <div
            className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all duration-300 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, progress_percent))}%` }}
          />
        </div>
      </div>

      {/* Aggregate Counts Grid */}
      <div className="grid grid-cols-5 gap-3 pt-1 text-center">
        {/* Total Files */}
        <div className="bg-dark-900/50 border border-dark-700/50 rounded-xl p-2.5">
          <span className="text-[10px] uppercase font-medium text-slate-400 block">Total Files</span>
          <span className="text-base font-bold font-mono text-white mt-0.5 block">{total_files}</span>
        </div>

        {/* Indexed */}
        <div className="bg-emerald-950/30 border border-emerald-500/20 rounded-xl p-2.5">
          <span className="text-[10px] uppercase font-medium text-emerald-400 block">Indexed</span>
          <span className="text-base font-bold font-mono text-emerald-300 mt-0.5 block">{indexed}</span>
        </div>

        {/* Queued & Processing */}
        <div className="bg-indigo-950/30 border border-indigo-500/20 rounded-xl p-2.5">
          <span className="text-[10px] uppercase font-medium text-indigo-400 block">In Queue</span>
          <span className="text-base font-bold font-mono text-indigo-300 mt-0.5 block">
            {queued + processing}
          </span>
        </div>

        {/* Skipped */}
        <div className="bg-dark-900/50 border border-dark-700/50 rounded-xl p-2.5">
          <span className="text-[10px] uppercase font-medium text-slate-400 block">Skipped</span>
          <span className="text-base font-bold font-mono text-slate-300 mt-0.5 block">{skipped}</span>
        </div>

        {/* Failed */}
        <div className="bg-rose-950/30 border border-rose-500/20 rounded-xl p-2.5">
          <span className="text-[10px] uppercase font-medium text-rose-400 block">Failed</span>
          <span className="text-base font-bold font-mono text-rose-300 mt-0.5 block">{failed}</span>
        </div>
      </div>
    </div>
  );
}
