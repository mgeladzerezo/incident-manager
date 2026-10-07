import { incident } from "../test-utils";
import { groupByStatus, hasRole } from "./incidents";

describe("groupByStatus", () => {
  it("puts each incident in the column for its status and keeps the order", () => {
    const columns = groupByStatus([
      incident({ id: 3, status: "open" }),
      incident({ id: 2, status: "resolved" }),
      incident({ id: 1, status: "open" }),
    ]);

    expect(columns.open.map((i) => i.id)).toEqual([3, 1]);
    expect(columns.acknowledged).toEqual([]);
    expect(columns.resolved.map((i) => i.id)).toEqual([2]);
  });

  it("returns all three columns for an empty list", () => {
    expect(groupByStatus([])).toEqual({ open: [], acknowledged: [], resolved: [] });
  });
});

describe("hasRole", () => {
  it("treats higher roles as including lower ones", () => {
    expect(hasRole(["admin"], "manager")).toBe(true);
    expect(hasRole(["manager"], "responder")).toBe(true);
    expect(hasRole(["manager"], "manager")).toBe(true);
  });

  it("does not grant a higher role than the user has", () => {
    expect(hasRole(["responder"], "manager")).toBe(false);
    expect(hasRole(["manager"], "admin")).toBe(false);
    expect(hasRole([], "responder")).toBe(false);
  });
});
