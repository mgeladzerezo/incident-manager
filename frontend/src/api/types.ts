import type { components } from "./schema";

type Schemas = components["schemas"];

export type IncidentStatus = Schemas["IncidentStatus"];
export type IncidentSummary = Schemas["IncidentSummary"];
export type IncidentDetail = Schemas["IncidentDetail"];
export type Alert = Schemas["AlertOut"];
export type TimelineEvent = Schemas["TimelineEventOut"];
export type Page = Schemas["PageOut"];
export type Postmortem = Schemas["PostmortemOut"];
export type PostmortemInput = Schemas["PostmortemIn"];
export type Schedule = Schemas["ScheduleOut"];
export type Shift = Schemas["ShiftOut"];
export type OverrideInput = Schemas["OverrideIn"];
export type Override = Schemas["OverrideOut"];
export type User = Schemas["UserOut"];
export type Me = Schemas["MeOut"];
export type Role = Schemas["Role"];
