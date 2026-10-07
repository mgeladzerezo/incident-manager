from prometheus_client import Counter, Gauge, Histogram

ALERTS_RECEIVED = Counter(
    "incident_manager_alerts_received_total",
    "Alerts received from Alertmanager by outcome.",
    ["outcome"],
)
INCIDENTS_OPENED = Counter(
    "incident_manager_incidents_opened_total", "Incidents created.", ["severity"]
)
ESCALATIONS = Counter(
    "incident_manager_escalations_total", "Escalation steps that paged someone.", ["level"]
)
PAGES = Counter("incident_manager_pages_total", "Page delivery attempts.", ["channel", "result"])
UNRESOLVED_INCIDENTS = Gauge(
    "incident_manager_unresolved_incidents", "Incidents not yet resolved.", ["status"]
)
WORKER_LAST_TICK = Gauge(
    "incident_manager_worker_last_tick_timestamp_seconds",
    "Unix time of the last completed worker loop. Alert when this goes stale.",
)
HTTP_REQUESTS = Counter(
    "incident_manager_http_requests_total", "HTTP requests.", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "incident_manager_http_request_duration_seconds", "HTTP request duration.", ["method", "route"]
)
