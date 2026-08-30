import { Database, CheckCircle2, HardDrive } from "lucide-react";

interface StateIndicatorProps {
  lastUpdatedTime: string | null;
  notification: string | null;
  totalFiles: number;
}

export function StateIndicator({
  lastUpdatedTime,
  notification,
  totalFiles,
}: StateIndicatorProps) {
  return (
    <footer className="h-9 px-6 bg-dark-900 border-t border-dark-700/60 flex items-center justify-between text-[11px] text-slate-400 font-mono select-none">
      {/* Left: SQLite Persistence status */}
      <div className="flex items-center space-x-2">
        <Database className="w-3.5 h-3.5 text-indigo-400" />
        <span>SQLite Store (%APPDATA%\FileMind\filemind.db)</span>
        <span className="text-slate-600">|</span>
        <span className="text-slate-300">{totalFiles} tracked entities</span>
      </div>

      {/* Center: Realtime Notification Toast */}
      {notification && (
        <div className="flex items-center space-x-1.5 text-indigo-300 animate-fade-in font-sans">
          <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-medium">{notification}</span>
        </div>
      )}

      {/* Right: Timestamp */}
      <div className="flex items-center space-x-2 text-slate-500">
        <HardDrive className="w-3 h-3 text-slate-500" />
        <span>
          {lastUpdatedTime
            ? `Sync: ${new Date(lastUpdatedTime).toLocaleTimeString()}`
            : "Initialized"}
        </span>
      </div>
    </footer>
  );
}
