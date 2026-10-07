import { useIncidents } from "../api/hooks";
import { IncidentCard } from "../components/IncidentCard";
import { groupByStatus, STATUS_LABEL, STATUSES } from "../lib/incidents";

export function BoardPage() {
  const incidents = useIncidents();

  if (incidents.isPending) return <p className="text-slate-500">Loading incidents…</p>;
  if (incidents.isError) {
    return <p className="text-red-700">Could not load incidents: {incidents.error.message}</p>;
  }

  const columns = groupByStatus(incidents.data);
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {STATUSES.map((status) => (
        <section key={status} aria-label={STATUS_LABEL[status]}>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            {STATUS_LABEL[status]} ({columns[status].length})
          </h2>
          <div className="space-y-3">
            {columns[status].map((incident) => (
              <IncidentCard key={incident.id} incident={incident} />
            ))}
            {columns[status].length === 0 && <p className="text-sm text-slate-400">Nothing here.</p>}
          </div>
        </section>
      ))}
    </div>
  );
}
