# Incident Manager

An incident and on-call manager. It receives alerts from Prometheus Alertmanager, groups
them into incidents, works out who is on call, pages them over Slack, Telegram and email,
and escalates to the next level if nobody acknowledges in time.

It is a portfolio project. The backend rules and the deployment are the part with depth;
the frontend is deliberately thin.

## What it does

- **Webhook receiver** for Alertmanager (`POST /api/v1/webhooks/alertmanager`), authenticated
  with a shared bearer token.
- **Grouping and deduplication.** Alerts with the same values for the grouping labels
  (default `alertname,service`) join one incident. A repeated delivery of the same alert
  (same fingerprint) only refreshes it. An incident resolves on its own once *all* of its
  alerts have resolved.
- **On-call schedules.** A rotation of people with a handoff at a fixed local time in the
  schedule's time zone, plus overrides for swaps and cover.
- **Escalation policies.** Ordered levels, each with a timeout and targets (a schedule or
  a person). Level 1 is paged when the incident opens; each timeout without an
  acknowledgement pages the next level.
- **Notifications** over Slack (bot DM), Telegram (bot message) and email (SMTP).
- **Login** through Keycloak (OIDC, authorization code + PKCE) with three roles:
  `responder` < `manager` < `admin`.
- **UI**: incident board (open / acknowledged / resolved), incident page with timeline,
  alerts and pages, on-call calendar (FullCalendar), postmortem editor (TipTap).
- **Prometheus metrics** on the API (`/metrics`) and on the worker (port 9100).

## Architecture

```
Alertmanager ──webhook──▶ API (FastAPI) ──┐
Browser ──(Keycloak token)──▶ API         ├──▶ PostgreSQL (CloudNativePG, 3 instances, WAL ▶ S3)
                                          │
              worker (polling loop) ──────┘──▶ Slack / Telegram / SMTP
```

| Path | Contents |
|------|----------|
| `backend/app/services/alerts.py` | Alert ingestion: grouping, deduplication, auto-resolve |
| `backend/app/services/oncall.py` | "Who is on call at T": pure functions, no database |
| `backend/app/services/escalation.py` | Escalation state machine, driven by a passed-in time |
| `backend/app/services/delivery.py` | Sends queued pages, with retries |
| `backend/app/notifications/` | Slack, Telegram and email senders behind one small interface |
| `backend/app/auth.py`, `api/deps.py` | Token verification, role checks, webhook token |
| `backend/app/worker.py` | The polling worker process |
| `backend/migrations/` | Alembic migrations |
| `frontend/` | React + TypeScript + Vite + Tailwind + TanStack Query |
| `deploy/helm/incident-manager/` | Helm chart, including the CloudNativePG `Cluster` |
| `deploy/terraform/` | VPC, EKS, backup bucket, IAM |
| `docs/dr-drill.md` | Database disaster recovery drill (procedure; not yet executed) |

There are two processes built from one backend image. The **API** handles the webhook and
the UI. The **worker** wakes up every few seconds, escalates incidents whose deadline has
passed and sends queued pages. All state is in PostgreSQL; there is no broker or cache.

### How the core rules work

**Grouping.** Each alert has a *fingerprint* (Alertmanager's, or a hash of its labels) and a
*group key* (hash of the grouping label values). A firing alert goes into the unresolved
incident with its group key, or opens one. A partial unique index
(`group_key WHERE status <> 'resolved'`) guarantees at most one unresolved incident per
group even when two webhook deliveries race; the loser catches the constraint violation
and joins the winner's incident. A resolved alert marks its row resolved, and the incident
closes when no firing alert is left. Once an incident is resolved, the same alert firing
again opens a new incident.

**On call.** Shift *n* of a rotation starts at `rotation_start + n × shift_length_days`
computed on the local calendar of the schedule's time zone and then converted to UTC. A
"Mondays 09:00" handoff therefore stays at 09:00 local time across daylight saving changes
(the UTC instant moves). Overrides are absolute `[start, end)` intervals and beat the
rotation; if overrides overlap, the most recently created wins. The calendar view asks
the same function once per stretch between handoffs and override edges, so it cannot
disagree with the pager.

**Escalation.** The incident row carries `escalation_level` and `next_escalation_at`.
Opening an incident pages level 1 and sets the deadline. The worker selects open incidents
whose deadline has passed (`FOR UPDATE SKIP LOCKED`), pages the next level and sets the
next deadline. Acknowledging or resolving clears the deadline. Nothing in this code reads
the system clock; the current time is an argument, and tests pass a fake clock.
"Never double-pages" rests on three things: the level counter only moves forward inside
the same transaction that writes the pages, the row lock keeps two workers off the same
incident, and a unique constraint on `(incident, level, user, channel)` backs both up.

**Paging is an outbox.** Escalation only inserts `pages` rows with status `pending`.
The worker sends them one by one, each in its own transaction, up to three attempts.
A slow Slack API therefore cannot delay the webhook response or the escalation
transaction. A page still queued when its incident is acknowledged is cancelled.

**Auth.** User requests carry a Keycloak access token; the API verifies the RS256 signature
against the realm's JWKS, plus issuer, audience and expiry, and reads roles from
`realm_access.roles`. The webhook uses a separate shared token compared in constant time;
an unset token rejects everything rather than opening the endpoint. Role rules:

| Action | Minimum role |
|--------|--------------|
| View everything, acknowledge, resolve, add notes, draft postmortems | responder |
| Create an override for yourself; edit your own contact details | responder |
| Manage schedules and escalation policies; overrides for others; publish postmortems | manager |
| Create users; edit other people's contact details | admin |

**Routing.** An alert with the label `escalation_policy: <name>` uses that policy;
everything else uses the policy marked as default.

## Running it

### Tests (no services needed)

Backend, from `backend/`:

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\python -m pytest
```

The suite runs against in-memory SQLite, a fake clock, tokens signed with a key generated
in the test session, and fakes for Slack, Telegram and SMTP (the real notifier classes are
tested against `httpx.MockTransport` and a fake SMTP class).

Frontend, from `frontend/`:

```
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

### Local stack

```
docker compose up --build
```

starts PostgreSQL, Keycloak (realm imported from `deploy/compose/keycloak-realm.json`),
Mailpit, the migration job, the API (port 8104), the worker and the frontend
(http://localhost:5174). Users `alice` (responder), `mona` (manager) and `adam` (admin)
have the password `password`. Send a test alert:

```
curl -X POST http://localhost:8104/api/v1/webhooks/alertmanager \
  -H "Authorization: Bearer local-webhook-token" -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"HighErrorRate","service":"checkout","severity":"critical"},"annotations":{"summary":"Checkout is failing"},"startsAt":"2026-01-01T00:00:00Z"}]}'
```

Schedules, policies and users are managed through the API (`/docs` lists it); the UI has
no forms for them yet.

**The compose stack has not been started on the development machine** (no Docker daemon
there), so treat it as unverified until someone runs it. See "Verification status".

### Frontend against a local API

`npm run dev` serves on port 5174 and proxies `/api` to `localhost:8104`. Settings come
from `public/config.js`, not from build-time variables, so the same image works in every
environment (in Kubernetes the file is mounted from a ConfigMap).

The TypeScript API types in `frontend/src/api/schema.d.ts` are generated from the
backend's OpenAPI document:

```
cd backend  && .venv\Scripts\python -m app.export_openapi ..\frontend\openapi.json
cd frontend && npm run gen:api
```

CI regenerates both and fails if the committed files differ.

## Deployment

### Terraform (`deploy/terraform`)

Creates a VPC over three zones (public and private subnets, one NAT gateway per zone, an
S3 gateway endpoint), an EKS cluster with a managed node group in the private subnets, the
EBS CSI add-on, a versioned and KMS-encrypted S3 bucket for database backups, and an IAM
role that only the database's service account can assume (IRSA).

```
terraform init -backend-config=backend.hcl
terraform apply -var-file=terraform.tfvars
```

Outputs `backup_bucket` and `backup_role_arn` feed the Helm values.

### Helm (`deploy/helm/incident-manager`)

Prerequisites: the CloudNativePG operator, an ingress controller, and a Secret (default
name `incident-manager`) with `webhook-token` and optionally `slack-bot-token`,
`telegram-bot-token`, `smtp-password`.

```
helm install incident-manager deploy/helm/incident-manager -n incident-manager \
  --set postgres.backup.destinationPath=s3://<backup_bucket>/cnpg \
  --set postgres.backup.iamRoleArn=<backup_role_arn> \
  --set config.oidcIssuer=https://keycloak.example.com/realms/incident \
  --set ingress.host=incidents.example.com --set config.publicUrl=https://incidents.example.com
```

What the chart does to keep the tool up when other things are down:

- API ×3, worker ×2, frontend ×2. Each Deployment has a zone topology spread constraint
  (`DoNotSchedule`, `maxSkew: 1`) and a softer per-host one, a PodDisruptionBudget, and
  rolls with `maxUnavailable: 0`.
- API readiness checks the database, liveness does not: during a database failover pods
  leave the Service and come back, instead of being restarted.
- PostgreSQL is a CloudNativePG `Cluster` with three instances, required anti-affinity
  across zones, one synchronous standby, WAL archiving and daily base backups to S3
  (`barmanObjectStore`), which is what makes point-in-time recovery possible. Setting
  `postgres.recovery.enabled` bootstraps the cluster from the object store instead.
- Migrations run as a Helm hook job (`post-install,pre-upgrade`).
- Optional `ServiceMonitor` and `PrometheusRule`, including an alert for "no worker has
  completed a pass in a minute". That alert must be routed somewhere other than this tool.

`docs/dr-drill.md` is the step-by-step procedure for killing the primary and for a full
restore from S3, with tables for the measured RTO and RPO. It has not been run; the tables
are empty.

### CI (`.github/workflows/ci.yml`)

Backend lint and tests; migrations applied up, down and up against a PostgreSQL service
container; frontend lint, type check, tests and build; API type drift check;
`terraform fmt`/`validate`, `helm lint`/`template` and a Trivy config scan; image builds
with a Trivy image scan that fails on fixable HIGH/CRITICAL findings.

## Decisions and trade-offs

- **Polling worker instead of Celery.** The only background job is "check for due
  escalations and pending pages". A loop with `SELECT … FOR UPDATE SKIP LOCKED` does that
  with no broker to run, monitor and lose. The cost is latency: a page goes out up to one
  poll interval (5 s by default) after it is queued, and this would not suit high-volume
  fan-out.
- **Deadline stored on the incident, not timers.** Escalation survives restarts because
  there is nothing in memory. A late worker gives the next level its full timeout counted
  from when it was actually paged, and advances one level per pass, rather than firing
  several levels at once after an outage.
- **At-least-once page delivery.** If the worker dies between a successful send and the
  commit, the page is sent again on the next pass. For a pager a duplicate is better than
  a miss.
- **Grouping in the application, by a fixed label set.** One global setting, simple to
  reason about. Per-service grouping rules would be the next step.
- **Roles come from the token, not the database.** Keycloak stays the single place where
  access is granted. A role change applies when the user's token is refreshed.
- **Wall-clock rotations in whole days.** Covers daily and weekly rotations and keeps DST
  handling in one place. Follow-the-sun shifts shorter than a day are not modelled.
- **SQLite in tests, PostgreSQL in production.** Tests run anywhere in seconds. The price
  is that row locking (`FOR UPDATE`, `SKIP LOCKED`) is a no-op on SQLite, so concurrency
  between workers is argued from the design and backed by unique constraints, not
  demonstrated by a test. Migrations do get applied to real PostgreSQL in CI.
- **Hand-written Terraform resources instead of the community EKS/VPC modules.** More
  lines, but every resource is visible and explainable.
- **One NAT gateway per zone.** Costs more than a shared one; with a shared one, losing
  its zone would cut every node off from Slack, Telegram and S3.
- **Synchronous replication with one standby.** Trades a little write latency for not
  losing acknowledged writes when the primary dies.

## Known limitations

- No UI for managing schedules, escalation policies or users; those go through the API.
  The calendar can add overrides but not delete them.
- One rotation per schedule (no layers), shifts in whole days, no per-weekday rules.
- An escalation policy ends after its last level; it does not repeat.
- Resolving an incident by hand while its alerts are still firing means Alertmanager's
  next repeat opens a new incident. There is no snooze or silence.
- No acknowledgement from Slack/Telegram; acknowledging happens in the UI or API.
- Failed pages are retried up to three times on consecutive polls without backoff, then
  marked failed. A failed level is not treated as "nobody reachable"; the normal timeout
  applies before the next level is paged.
- A user pre-created by an admin is linked to the first login with the same email, which
  assumes Keycloak only issues verified email addresses.
- The webhook token is a single shared secret; rotating it means updating Alertmanager and
  the Secret together.
- The chart uses CloudNativePG's in-tree `barmanObjectStore` configuration. Newer operator
  releases move this to the Barman Cloud plugin; the manifest will need adjusting then.
- `.terraform.lock.hcl` is not committed: it was generated on Windows only and would not
  contain Linux provider hashes. Run `terraform providers lock` for the platforms you use.

## Verification status

Run on the development machine (Windows, no Docker daemon, no cloud account):

- Backend: `ruff check`, `ruff format --check`, `pytest` (SQLite).
- Frontend: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- `alembic upgrade head` against a SQLite file, and the API process started once on that
  database to check `/healthz`, `/readyz`, `/metrics` and the webhook over real HTTP.
- `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`.
- `helm lint` and `helm template`, including recovery mode.

Written but not executed anywhere yet:

- Anything against real PostgreSQL (migrations on PostgreSQL, row locking between workers).
- Docker image builds, `docker compose up`, the Keycloak realm import and the browser
  login flow. The UI has only been exercised through component tests, not in a browser
  against a live API.
- The GitHub Actions workflow.
- `terraform plan`/`apply`, installing the chart on a cluster, the CloudNativePG manifests
  against a real operator, and the DR drill.
- Real Slack, Telegram and SMTP endpoints.
