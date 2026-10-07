import { Link } from "react-router-dom";

import type { IncidentSummary } from "../api/types";
import { formatDateTime } from "../lib/format";
import { IncidentActions } from "./IncidentActions";

export function IncidentCard({ incident }: { incident: IncidentSummary }) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <Link to={`/incidents/${incident.id}`} className="font-medium hover:underline">
          #{incident.id} {incident.title}
        </Link>
        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs uppercase text-slate-600">
          {incident.severity}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {incident.firing_alert_count} of {incident.alert_count} alerts firing · opened{" "}
        {formatDateTime(incident.created_at)}
      </p>
      {incident.status === "open" && incident.escalation_level > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Escalation level {incident.escalation_level}
        </p>
      )}
      {incident.acknowledged_by_name && incident.status === "acknowledged" && (
        <p className="mt-1 text-xs text-slate-500">
          Acknowledged by {incident.acknowledged_by_name}
        </p>
      )}
      <div className="mt-2">
        <IncidentActions id={incident.id} status={incident.status} />
      </div>
    </article>
  );
}
