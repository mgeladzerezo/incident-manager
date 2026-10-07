import { type FormEvent, useState } from "react";

import { useCreateOverride } from "../api/hooks";
import type { User } from "../api/types";

interface OverrideFormProps {
  scheduleId: number;
  // People the current user is allowed to put on call: everyone for managers, only
  // themselves for responders.
  candidates: User[];
}

const inputClass = "rounded border border-slate-300 px-2 py-1.5 text-sm";

export function OverrideForm({ scheduleId, candidates }: OverrideFormProps) {
  const [userId, setUserId] = useState(candidates[0]?.id);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const createOverride = useCreateOverride(scheduleId);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (userId === undefined || !start || !end) return;
    createOverride.mutate(
      // datetime-local values are in the browser's time zone; send absolute instants.
      { user_id: userId, starts_at: new Date(start).toISOString(), ends_at: new Date(end).toISOString() },
      {
        onSuccess: () => {
          setStart("");
          setEnd("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col text-xs text-slate-500">
        Who
        <select
          className={inputClass}
          value={userId}
          onChange={(event) => setUserId(Number(event.target.value))}
        >
          {candidates.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-xs text-slate-500">
        From
        <input
          type="datetime-local"
          className={inputClass}
          value={start}
          onChange={(event) => setStart(event.target.value)}
          required
        />
      </label>
      <label className="flex flex-col text-xs text-slate-500">
        Until
        <input
          type="datetime-local"
          className={inputClass}
          value={end}
          min={start}
          onChange={(event) => setEnd(event.target.value)}
          required
        />
      </label>
      <button
        className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={createOverride.isPending}
      >
        Add override
      </button>
      {createOverride.isError && (
        <span className="text-sm text-red-700">{createOverride.error.message}</span>
      )}
    </form>
  );
}
