import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BoardPage } from "./pages/BoardPage";

// The calendar and the editor are the two heavy dependencies; load them only on the pages
// that use them so the board, which is what people open during an incident, stays small.
const CalendarPage = lazy(() =>
  import("./pages/CalendarPage").then((module) => ({ default: module.CalendarPage })),
);
const IncidentPage = lazy(() =>
  import("./pages/IncidentPage").then((module) => ({ default: module.IncidentPage })),
);

export function App() {
  return (
    <Suspense fallback={<p className="p-8 text-slate-500">Loading…</p>}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<BoardPage />} />
          <Route path="incidents/:incidentId" element={<IncidentPage />} />
          <Route path="on-call" element={<CalendarPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
