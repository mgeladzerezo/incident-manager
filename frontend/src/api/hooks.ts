import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "./client";
import type {
  IncidentDetail,
  IncidentSummary,
  Me,
  Override,
  OverrideInput,
  Postmortem,
  PostmortemInput,
  Schedule,
  Shift,
  User,
} from "./types";

const REFRESH_MS = 10_000;

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), staleTime: Infinity });
}

export function useUsers() {
  return useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
}

export function useIncidents() {
  return useQuery({
    queryKey: ["incidents"],
    queryFn: () => api<IncidentSummary[]>("/incidents"),
    refetchInterval: REFRESH_MS,
  });
}

export function useIncident(id: number) {
  return useQuery({
    queryKey: ["incidents", id],
    queryFn: () => api<IncidentDetail>(`/incidents/${id}`),
    refetchInterval: REFRESH_MS,
  });
}

export type IncidentAction = "acknowledge" | "resolve";

export function useIncidentAction(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: IncidentAction) =>
      api<IncidentDetail>(`/incidents/${id}/${action}`, { method: "POST" }),
    onSuccess: (incident) => {
      queryClient.setQueryData(["incidents", id], incident);
      return queryClient.invalidateQueries({ queryKey: ["incidents"], exact: true });
    },
  });
}

export function useAddNote(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<IncidentDetail>(`/incidents/${id}/notes`, {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    onSuccess: (incident) => queryClient.setQueryData(["incidents", id], incident),
  });
}

export function usePostmortem(incidentId: number) {
  return useQuery({
    queryKey: ["postmortem", incidentId],
    // A missing postmortem is the normal state for a new incident, not an error.
    queryFn: async () => {
      try {
        return await api<Postmortem>(`/incidents/${incidentId}/postmortem`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export function useSavePostmortem(incidentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: PostmortemInput) =>
      api<Postmortem>(`/incidents/${incidentId}/postmortem`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    onSuccess: (postmortem) => queryClient.setQueryData(["postmortem", incidentId], postmortem),
  });
}

export function useSchedules() {
  return useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules") });
}

export interface DateRange {
  start: string;
  end: string;
}

export function useShifts(scheduleId: number | undefined, range: DateRange | undefined) {
  return useQuery({
    queryKey: ["shifts", scheduleId, range?.start, range?.end],
    queryFn: () => {
      const params = new URLSearchParams({ start: range!.start, end: range!.end });
      return api<Shift[]>(`/schedules/${scheduleId}/shifts?${params}`);
    },
    enabled: scheduleId !== undefined && range !== undefined,
  });
}

export function useCreateOverride(scheduleId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: OverrideInput) =>
      api<Override>(`/schedules/${scheduleId}/overrides`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["shifts", scheduleId] }),
        queryClient.invalidateQueries({ queryKey: ["schedules"] }),
      ]),
  });
}
