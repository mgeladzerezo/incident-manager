import type { TimelineEvent } from "../api/types";
import { formatDateTime } from "../lib/format";

const DOT: Record<string, string> = {
  opened: "bg-red-500",
  page: "bg-violet-500",
  escalation: "bg-violet-300",
  acknowledged: "bg-amber-500",
  resolved: "bg-emerald-500",
  note: "bg-sky-500",
};

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="space-y-3 border-l border-slate-200 pl-4">
      {events.map((event) => (
        <li key={event.id} className="relative">
          <span
            className={`absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ${DOT[event.kind] ?? "bg-slate-400"}`}
          />
          <p className="text-sm">{event.message}</p>
          <p className="text-xs text-slate-500">
            <time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>
            {event.kind === "note" && event.actor_name && ` · ${event.actor_name}`}
          </p>
        </li>
      ))}
    </ol>
  );
}
