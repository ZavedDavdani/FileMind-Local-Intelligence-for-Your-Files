import { useState } from "react";
import { EventItem } from "../types";
import { History, ChevronDown, ChevronUp } from "lucide-react";

interface EventAuditLogProps {
  events: EventItem[];
}

function getEventBadge(type: string) {
  switch (type) {
    case "CREATE":
      return (
        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-emerald-950/70 text-emerald-300 border border-emerald-500/40">
          CREATE
        </span>
      );
    case "MODIFY":
      return (
        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-indigo-950/70 text-indigo-300 border border-indigo-500/40">
          MODIFY
        </span>
      );
    case "DELETE":
      return (
        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-rose-950/70 text-rose-300 border border-rose-500/40">
          DELETE
        </span>
      );
    case "RENAME":
    case "MOVE":
      return (
        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-amber-950/70 text-amber-300 border border-amber-500/40">
          {type}
        </span>
      );
    default:
      return null;
  }
}

export function EventAuditLog({ events = [] }: EventAuditLogProps) {
  const [isOpen, setIsOpen] = useState(false);
  const safeEvents = Array.isArray(events) ? events : [];

  return (
    <div className="bg-dark-800/40 border border-dark-700/60 rounded-xl overflow-hidden text-xs">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-2.5 flex items-center justify-between hover:bg-dark-700/30 transition-colors text-slate-300 font-medium"
      >
        <div className="flex items-center space-x-2">
          <History className="w-4 h-4 text-indigo-400" />
          <span>Filesystem Event Audit Trail</span>
          <span className="bg-dark-700 px-1.5 py-0.5 rounded text-[10px] text-slate-400 font-mono">
            {safeEvents.length}
          </span>
        </div>
        {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {isOpen && (
        <div className="max-h-48 overflow-y-auto border-t border-dark-700/60 divide-y divide-dark-700/40 p-2 font-mono text-[11px]">
          {safeEvents.length === 0 && (
            <div className="p-4 text-center text-slate-500">No events observed yet.</div>
          )}
          {safeEvents.map((ev) => (
            <div key={ev.event_id} className="py-1.5 px-2 flex items-center justify-between hover:bg-dark-700/20">
              <div className="flex items-center space-x-2.5 min-w-0 flex-1 pr-4">
                {getEventBadge(ev.event_type)}
                <span className="text-slate-300 truncate" title={ev.path}>
                  {ev.path}
                </span>
                {ev.old_path && (
                  <span className="text-slate-500 flex items-center space-x-1 shrink-0">
                    <span>from</span>
                    <span className="truncate max-w-[120px]">{ev.old_path}</span>
                  </span>
                )}
              </div>
              <span className="text-[10px] text-slate-500 shrink-0">
                {ev.observed_at ? new Date(ev.observed_at).toLocaleTimeString() : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
