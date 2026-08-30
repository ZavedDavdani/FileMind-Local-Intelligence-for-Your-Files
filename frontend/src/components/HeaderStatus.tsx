import { XCircle, RefreshCw, Activity, ShieldCheck, Loader2 } from "lucide-react";
import { HealthResponse } from "../types";

interface HeaderStatusProps {
  status: "checking" | "online" | "unavailable";
  healthData: HealthResponse | null;
  latencyMs: number | null;
  isIndexing?: boolean;
  onRetry: () => void;
}

export function HeaderStatus({
  status,
  healthData,
  latencyMs,
  isIndexing,
  onRetry,
}: HeaderStatusProps) {
  return (
    <header className="h-16 px-6 border-b border-dark-700/60 bg-dark-800/40 backdrop-blur-md flex items-center justify-between select-none">
      {/* Brand & Identity */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center">
          <ShieldCheck className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="font-bold text-sm tracking-tight text-white">FileMind</h1>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-indigo-950/80 text-indigo-300 border border-indigo-500/30">
              Phase 1
            </span>
          </div>
          <p className="text-[11px] text-slate-400">Local Filesystem Engine</p>
        </div>
      </div>

      {/* Backend Status & Live Indicator */}
      <div className="flex items-center space-x-3">
        {isIndexing && (
          <div className="flex items-center space-x-1.5 bg-indigo-950/50 border border-indigo-500/30 px-3 py-1 rounded-full text-xs text-indigo-300">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
            <span className="font-medium">Indexing...</span>
          </div>
        )}

        {status === "online" && (
          <div className="flex items-center space-x-2 bg-emerald-950/40 border border-emerald-500/30 px-3 py-1.5 rounded-full text-xs text-emerald-300">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="font-medium">Backend Online</span>
            {healthData && (
              <span className="text-[10px] text-emerald-400/80 font-mono">
                :24823 ({latencyMs}ms)
              </span>
            )}
          </div>
        )}

        {status === "unavailable" && (
          <div className="flex items-center space-x-2 bg-rose-950/40 border border-rose-500/30 px-3 py-1.5 rounded-full text-xs text-rose-300">
            <XCircle className="w-3.5 h-3.5 text-rose-400" />
            <span className="font-medium">Backend Unavailable</span>
            <button
              onClick={onRetry}
              className="ml-1 hover:text-white transition-colors flex items-center space-x-1"
              title="Retry connection"
            >
              <RefreshCw className="w-3 h-3 animate-spin-hover" />
            </button>
          </div>
        )}

        {status === "checking" && (
          <div className="flex items-center space-x-2 bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-full text-xs text-slate-300">
            <Activity className="w-3.5 h-3.5 text-slate-400 animate-pulse" />
            <span>Connecting...</span>
          </div>
        )}
      </div>
    </header>
  );
}
