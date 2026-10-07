import { type FormEvent, useState } from "react";

import { useAddNote } from "../api/hooks";

export function NoteForm({ incidentId }: { incidentId: number }) {
  const [text, setText] = useState("");
  const addNote = useAddNote(incidentId);

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    addNote.mutate(trimmed, { onSuccess: () => setText("") });
  }

  return (
    <form onSubmit={submit} className="mt-4 flex gap-2">
      <input
        aria-label="Timeline note"
        className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm"
        placeholder="Add a note to the timeline"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <button
        className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        disabled={addNote.isPending || !text.trim()}
      >
        Add note
      </button>
    </form>
  );
}
