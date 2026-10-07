import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useIncident } from "../api/hooks";
import type { Alert, IncidentDetail, Page } from "../api/types";
import { IncidentActions } from "../components/IncidentActions";
import { NoteForm } from "../components/NoteForm";
import { PostmortemEditor } from "../components/PostmortemEditor";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { formatDateTime, formatDuration } from "../lib/format";

export function IncidentPage() {
  const { incidentId } = useParams();
  const id = Number(incidentId);
  const incident = useIncident(id);

  if (incident.isPending) return <p className="text-slate-500">Loading incident…</p>;
  if (incident.isError) {
    return <p className="text-red-700">Could not load incident: {incident.error.message}</p>;
  }
  return <IncidentView incident={incident.data} />;
}

function IncidentView({ incident }: { incident: IncidentDetail }) {
  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-slate-500 hover:underline">
          ← All incidents
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">
            #{incident.id} {incident.title}
          </h1>
          <StatusBadge status={incident.status} />
          <IncidentActions id={incident.id} status={incident.status} />
        </div>
        <p className="mt-1 text-sm text-slate-500">{summaryLine(incident)}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Timeline">
          <Timeline events={incident.timeline} />
          <NoteForm incidentId={incident.id} />
        </Section>
        <div className="space-y-6">
          <Section title={`Alerts (${incident.firing_alert_count} firing)`}>
            <AlertTable alerts={incident.alerts} />
          </Section>
          <Section title="Pages">
            <PageTable pages={incident.pages} />
          </Section>
        </div>
      </div>

      <Section title="Postmortem">
        <PostmortemEditor incidentId={incident.id} />
      </Section>
    </div>
  );
}

function summaryLine(incident: IncidentDetail): string {
  const parts = [
    `Severity ${incident.severity}`,
    `opened ${formatDateTime(incident.created_at)}`,
    `policy ${incident.policy_name ?? "none"}`,
  ];
  if (incident.acknowledged_at) {
    parts.push(`acknowledged after ${formatDuration(incident.created_at, incident.acknowledged_at)}`);
  }
  if (incident.resolved_at) {
    parts.push(`resolved after ${formatDuration(incident.created_at, incident.resolved_at)}`);
  }
  if (incident.next_escalation_at) {
    parts.push(`next escalation ${formatDateTime(incident.next_escalation_at)}`);
  }
  return parts.join(" · ");
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

function AlertTable({ alerts }: { alerts: Alert[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 font-medium">Alert</th>
          <th className="py-1 font-medium">Instance</th>
          <th className="py-1 font-medium">State</th>
          <th className="py-1 font-medium">Since</th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((alert) => (
          <tr key={alert.id} className="border-t border-slate-200">
            <td className="py-1.5">{alert.labels.alertname ?? "alert"}</td>
            <td className="py-1.5">{alert.labels.instance ?? "—"}</td>
            <td className={`py-1.5 ${alert.status === "firing" ? "text-red-700" : "text-emerald-700"}`}>
              {alert.status}
            </td>
            <td className="py-1.5 text-slate-500">{formatDateTime(alert.starts_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PageTable({ pages }: { pages: Page[] }) {
  if (pages.length === 0) return <p className="text-sm text-slate-400">Nobody was paged.</p>;
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 font-medium">Level</th>
          <th className="py-1 font-medium">Who</th>
          <th className="py-1 font-medium">Channel</th>
          <th className="py-1 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {pages.map((page) => (
          <tr key={page.id} className="border-t border-slate-200">
            <td className="py-1.5">{page.level}</td>
            <td className="py-1.5">{page.user_name}</td>
            <td className="py-1.5">{page.channel}</td>
            <td className="py-1.5" title={page.last_error ?? undefined}>
              {page.status}
              {page.sent_at && ` ${formatDateTime(page.sent_at)}`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
