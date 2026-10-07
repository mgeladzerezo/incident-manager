import type { IncidentStatus } from "../api/types";
import { STATUS_LABEL } from "../lib/incidents";

const STYLE: Record<IncidentStatus, string> = {
  open: "bg-red-100 text-red-800",
  acknowledged: "bg-amber-100 text-amber-800",
  resolved: "bg-emerald-100 text-emerald-800",
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
