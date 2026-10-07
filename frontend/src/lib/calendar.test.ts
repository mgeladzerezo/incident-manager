import type { Shift, User } from "../api/types";
import { shiftsToEvents } from "./calendar";
import { formatDuration } from "./format";

const ana: User = {
  id: 1,
  name: "Ana",
  email: "ana@example.com",
  slack_user_id: null,
  telegram_chat_id: null,
};
const ben: User = { ...ana, id: 2, name: "Ben", email: "ben@example.com" };

function shift(user: User, source: Shift["source"], starts_at: string, ends_at: string): Shift {
  return { user, source, starts_at, ends_at };
}

describe("shiftsToEvents", () => {
  it("maps each shift to a calendar event with the same bounds", () => {
    const [event] = shiftsToEvents([
      shift(ana, "rotation", "2026-03-02T08:00:00Z", "2026-03-09T08:00:00Z"),
    ]);

    expect(event).toMatchObject({
      title: "Ana",
      start: "2026-03-02T08:00:00Z",
      end: "2026-03-09T08:00:00Z",
    });
  });

  it("marks overrides in the title and gives them a distinct colour", () => {
    const [rotation, override] = shiftsToEvents([
      shift(ben, "rotation", "2026-03-02T08:00:00Z", "2026-03-03T00:00:00Z"),
      shift(ben, "override", "2026-03-03T00:00:00Z", "2026-03-04T00:00:00Z"),
    ]);

    expect(override?.title).toBe("Ben (override)");
    expect(override?.backgroundColor).not.toBe(rotation?.backgroundColor);
  });

  it("gives the same person the same colour across shifts", () => {
    const events = shiftsToEvents([
      shift(ana, "rotation", "2026-03-02T08:00:00Z", "2026-03-09T08:00:00Z"),
      shift(ben, "rotation", "2026-03-09T08:00:00Z", "2026-03-16T08:00:00Z"),
      shift(ana, "rotation", "2026-03-16T08:00:00Z", "2026-03-23T08:00:00Z"),
    ]);

    expect(events[0]?.backgroundColor).toBe(events[2]?.backgroundColor);
    expect(events[0]?.backgroundColor).not.toBe(events[1]?.backgroundColor);
  });
});

describe("formatDuration", () => {
  it.each([
    ["2026-03-02T12:00:00Z", "2026-03-02T12:04:20Z", "4m"],
    ["2026-03-02T12:00:00Z", "2026-03-02T14:05:00Z", "2h 5m"],
    ["2026-03-02T12:00:00Z", "2026-03-04T15:00:00Z", "2d 3h"],
    ["2026-03-02T12:00:00Z", "2026-03-02T11:00:00Z", "0m"],
  ])("formats %s to %s as %s", (from, to, expected) => {
    expect(formatDuration(from, to)).toBe(expected);
  });
});
