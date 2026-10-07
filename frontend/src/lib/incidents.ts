import type { IncidentStatus, IncidentSummary, Role } from "../api/types";

export const STATUSES: IncidentStatus[] = ["open", "acknowledged", "resolved"];

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export function groupByStatus(
  incidents: IncidentSummary[],
): Record<IncidentStatus, IncidentSummary[]> {
  const columns: Record<IncidentStatus, IncidentSummary[]> = {
    open: [],
    acknowledged: [],
    resolved: [],
  };
  for (const incident of incidents) {
    columns[incident.status].push(incident);
  }
  return columns;
}

const ROLE_RANK: Record<Role, number> = { responder: 1, manager: 2, admin: 3 };

// Mirrors the backend rule that a higher role includes the lower ones. Only used to hide
// controls; the API is what enforces it.
export function hasRole(roles: Role[], required: Role): boolean {
  return roles.some((role) => ROLE_RANK[role] >= ROLE_RANK[required]);
}
