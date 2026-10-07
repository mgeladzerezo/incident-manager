import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import type { IncidentSummary } from "./api/types";

export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function incident(overrides: Partial<IncidentSummary> = {}): IncidentSummary {
  return {
    id: 1,
    title: "HighErrorRate on checkout",
    severity: "critical",
    status: "open",
    group_labels: { alertname: "HighErrorRate", service: "checkout" },
    escalation_level: 1,
    alert_count: 2,
    firing_alert_count: 2,
    created_at: "2026-03-02T12:00:00Z",
    acknowledged_at: null,
    acknowledged_by_name: null,
    resolved_at: null,
    resolved_by_name: null,
    ...overrides,
  };
}

type Handler = (request: { method: string; path: string }) => unknown;

// Replaces fetch with a function that answers from `handler` and records the calls.
export function mockApi(handler: Handler) {
  const calls: { method: string; path: string }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { method: init?.method ?? "GET", path: String(input) };
    calls.push(call);
    return new Response(JSON.stringify(handler(call)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
