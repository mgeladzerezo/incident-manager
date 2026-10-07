import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { incident, mockApi, renderWithProviders } from "../test-utils";
import { BoardPage } from "./BoardPage";

afterEach(() => vi.unstubAllGlobals());

describe("BoardPage", () => {
  it("shows incidents in the column matching their status", async () => {
    mockApi(() => [
      incident({ id: 1, title: "Checkout errors", status: "open" }),
      incident({ id: 2, title: "Disk full", status: "acknowledged", acknowledged_by_name: "Ana" }),
      incident({ id: 3, title: "Old outage", status: "resolved", firing_alert_count: 0 }),
    ]);

    renderWithProviders(<BoardPage />);

    const open = await screen.findByRole("region", { name: "Open" });
    expect(within(open).getByText("#1 Checkout errors")).toBeInTheDocument();
    const acknowledged = screen.getByRole("region", { name: "Acknowledged" });
    expect(within(acknowledged).getByText("#2 Disk full")).toBeInTheDocument();
    expect(within(acknowledged).getByText("Acknowledged by Ana")).toBeInTheDocument();
    const resolved = screen.getByRole("region", { name: "Resolved" });
    expect(within(resolved).getByText("#3 Old outage")).toBeInTheDocument();
  });

  it("offers only the actions that make sense for each status", async () => {
    mockApi(() => [
      incident({ id: 1, status: "open" }),
      incident({ id: 2, status: "acknowledged" }),
      incident({ id: 3, status: "resolved" }),
    ]);

    renderWithProviders(<BoardPage />);

    const open = await screen.findByRole("region", { name: "Open" });
    expect(within(open).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(within(open).getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    const acknowledged = screen.getByRole("region", { name: "Acknowledged" });
    expect(within(acknowledged).queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(within(acknowledged).getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Resolved" })).queryAllByRole("button")).toEqual(
      [],
    );
  });

  it("acknowledging posts to the API for that incident", async () => {
    const calls = mockApi(({ method }) =>
      method === "POST" ? incident({ id: 7, status: "acknowledged" }) : [incident({ id: 7 })],
    );

    renderWithProviders(<BoardPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "POST", path: "/api/v1/incidents/7/acknowledge" }),
    );
  });

  it("shows an empty state per column", async () => {
    mockApi(() => []);

    renderWithProviders(<BoardPage />);

    expect(await screen.findAllByText("Nothing here.")).toHaveLength(3);
  });
});
