import { useIncidentAction } from "../api/hooks";
import type { IncidentStatus } from "../api/types";

const buttonClass =
  "rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50";

export function IncidentActions({ id, status }: { id: number; status: IncidentStatus }) {
  const action = useIncidentAction(id);
  if (status === "resolved") return null;

  return (
    <div className="flex items-center gap-2">
      {status === "open" && (
        <button
          className={buttonClass}
          disabled={action.isPending}
          onClick={() => action.mutate("acknowledge")}
        >
          Acknowledge
        </button>
      )}
      <button
        className={buttonClass}
        disabled={action.isPending}
        onClick={() => action.mutate("resolve")}
      >
        Resolve
      </button>
      {action.isError && <span className="text-xs text-red-700">{action.error.message}</span>}
    </div>
  );
}
