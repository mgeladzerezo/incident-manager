import type { EventInput } from "@fullcalendar/core";

import type { Shift } from "../api/types";

const PALETTE = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2"] as const;
const OVERRIDE_COLOR = "#dc2626";

export function shiftsToEvents(shifts: Shift[]): EventInput[] {
  return shifts.map((shift) => {
    const isOverride = shift.source === "override";
    return {
      id: `${shift.user.id}-${shift.starts_at}`,
      title: isOverride ? `${shift.user.name} (override)` : shift.user.name,
      start: shift.starts_at,
      end: shift.ends_at,
      backgroundColor: isOverride ? OVERRIDE_COLOR : colorFor(shift.user.id),
      borderColor: "transparent",
    };
  });
}

function colorFor(userId: number): string {
  return PALETTE[userId % PALETTE.length] ?? PALETTE[0];
}
