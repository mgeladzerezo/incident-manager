import dayGridPlugin from "@fullcalendar/daygrid";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { useMemo, useState } from "react";

import { type DateRange, useMe, useSchedules, useShifts, useUsers } from "../api/hooks";
import { OverrideForm } from "../components/OverrideForm";
import { shiftsToEvents } from "../lib/calendar";
import { hasRole } from "../lib/incidents";

export function CalendarPage() {
  const schedules = useSchedules();
  const me = useMe();
  const users = useUsers();
  const [selectedId, setSelectedId] = useState<number>();
  const [range, setRange] = useState<DateRange>();

  const schedule = schedules.data?.find((s) => s.id === selectedId) ?? schedules.data?.[0];
  const shifts = useShifts(schedule?.id, range);
  const events = useMemo(() => shiftsToEvents(shifts.data ?? []), [shifts.data]);

  if (schedules.isPending) return <p className="text-slate-500">Loading schedules…</p>;
  if (schedules.isError) {
    return <p className="text-red-700">Could not load schedules: {schedules.error.message}</p>;
  }
  if (schedule === undefined) {
    return <p className="text-slate-500">No schedules yet. A manager can create one via the API.</p>;
  }

  const isManager = hasRole(me.data?.roles ?? [], "manager");
  const candidates = isManager ? (users.data ?? []) : me.data ? [me.data.user] : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="Schedule"
          className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
          value={schedule.id}
          onChange={(event) => setSelectedId(Number(event.target.value))}
        >
          {schedules.data.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <p className="text-sm text-slate-500">
          {schedule.users.map((user) => user.name).join(" → ")} · every{" "}
          {schedule.shift_length_days} day(s) · handoff {schedule.rotation_start.slice(11, 16)}{" "}
          {schedule.timezone}
        </p>
      </div>

      {shifts.isError && <p className="text-sm text-red-700">{shifts.error.message}</p>}
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin]}
          initialView="dayGridMonth"
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek" }}
          height="auto"
          firstDay={1}
          events={events}
          // The calendar tells us which dates are visible; that range drives the shift query.
          datesSet={({ startStr, endStr }) => setRange({ start: startStr, end: endStr })}
        />
      </div>

      {candidates.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Override
          </h2>
          <OverrideForm key={schedule.id} scheduleId={schedule.id} candidates={candidates} />
        </section>
      )}
    </div>
  );
}
