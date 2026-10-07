# Disaster recovery drill: database

**Status: procedure only. This drill has not been executed yet.** The results tables at the
end are empty on purpose and must be filled in from a real run. Do not copy numbers into
them from anywhere else.

The drill answers two questions with measurements:

- **RTO** (recovery time objective): how long is the incident manager unable to accept
  alerts and page people?
- **RPO** (recovery point objective): how much acknowledged data is lost?

It has two parts because there are two different failures:

| Part | Failure | Recovery mechanism | Expectation to verify |
|------|---------|--------------------|-----------------------|
| A | The primary database instance dies | CloudNativePG promotes a synchronous standby | RPO of zero; RTO well under a minute |
| B | The whole database cluster and its volumes are gone | New cluster restored from S3 (base backup + WAL) | RPO bounded by `archive_timeout` (60 s); RTO dominated by restore time |

The expectations are what the design is supposed to deliver. The point of the drill is to
find out whether it does.

## Prerequisites

- A non-production cluster deployed from `deploy/terraform` and `deploy/helm` with at least
  three nodes in three zones. Do not run part B against production.
- `kubectl` with the [cnpg plugin](https://cloudnative-pg.io/documentation/current/kubectl-plugin/),
  `helm`, `aws`, `curl`.
- The webhook token.
- A default escalation policy that only targets a test user. The probe below opens one
  incident per second and every one of them pages level 1 of the default policy.

Set these once per shell:

```bash
export NS=incident-manager
export RELEASE=incident-manager
export DB=${RELEASE}-db                     # CloudNativePG Cluster name
export URL=https://incidents.example.com    # public URL of the deployment
export WEBHOOK_TOKEN=...                    # value of webhook-token in the app secret
export BUCKET=$(terraform -chdir=deploy/terraform output -raw backup_bucket)
```

Confirm the starting state. Stop here if anything is not healthy.

```bash
kubectl cnpg status $DB -n $NS
# Expect: 3 instances, "Cluster in healthy state", one standby with Sync State "quorum" or
# "sync", "Continuous Backup status" showing a first recoverability point and
# "Working WAL archiving: OK".

kubectl get backups.postgresql.cnpg.io -n $NS
# Expect: at least one backup with phase "completed".
```

## Probe: a writer that records what was acknowledged

Both parts use the same probe. It sends one uniquely numbered alert per second through the
real webhook and logs the time and HTTP status of every attempt. Afterwards the log shows
when the service was unavailable (RTO) and which acknowledged writes should exist (RPO).

Each alert has a distinct `service` label, so each one creates its own incident and can be
counted in the database.

```bash
probe() {
  local i=0
  while true; do
    i=$((i + 1))
    local sent=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
    local code=$(curl -s -o /dev/null -m 2 -w '%{http_code}' \
      -X POST "$URL/api/v1/webhooks/alertmanager" \
      -H "Authorization: Bearer $WEBHOOK_TOKEN" -H 'Content-Type: application/json' \
      -d "{\"alerts\":[{\"status\":\"firing\",\"labels\":{\"alertname\":\"DrDrill\",\"service\":\"drill-$RUN-$i\"},\"startsAt\":\"$sent\"}]}")
    echo "$sent $i $code" | tee -a "probe-$RUN.log"
    sleep 1
  done
}
```

Helper to count what the database actually contains for a run:

```bash
stored() {
  kubectl cnpg psql $DB -n $NS -- -d incident -At -c \
    "select count(*), max(created_at) from incidents where group_labels->>'service' like 'drill-$RUN-%'"
}
```

Read the log like this:

- **Outage start**: timestamp of the first line whose status is not `200`.
- **Outage end**: timestamp of the first `200` after which there are no more failures.
- **RTO** = outage end − outage start.
- **Acknowledged writes** = number of lines with status `200`:
  `awk '$3 == 200' probe-$RUN.log | wc -l`
- **RPO in records** = acknowledged writes − stored count. **RPO in time** = timestamp of
  the last acknowledged write before the outage − `max(created_at)` of what survived
  (zero if nothing acknowledged is missing).

## Part A: kill the primary

1. Start the probe in a second terminal and let it run for at least 30 seconds.

   ```bash
   export RUN=a-$(date -u +%H%M%S)
   probe
   ```

2. Find the primary and record the kill time.

   ```bash
   PRIMARY=$(kubectl get cluster $DB -n $NS -o jsonpath='{.status.currentPrimary}')
   echo "primary: $PRIMARY"
   date -u +%Y-%m-%dT%H:%M:%S.%3NZ   # record as "kill time"
   ```

3. Kill it without a graceful shutdown, which is what a node failure looks like to
   PostgreSQL.

   ```bash
   kubectl delete pod $PRIMARY -n $NS --grace-period=0 --force
   ```

4. Watch the failover.

   ```bash
   kubectl get cluster $DB -n $NS -w
   # Wait for STATUS "Cluster in healthy state" with a different PRIMARY.
   ```

   Record the time the new primary is reported, and the new primary's name.

5. Let the probe run for another 60 seconds after it returns to `200`, then stop it
   (Ctrl-C).

6. Collect the numbers.

   ```bash
   awk '$3 != 200' probe-$RUN.log | head -1    # outage start
   awk '$3 != 200' probe-$RUN.log | tail -1    # last failed request
   awk '$3 == 200' probe-$RUN.log | wc -l      # acknowledged writes
   stored                                      # rows present, newest timestamp
   ```

7. Check that the cluster healed itself: the killed instance should rejoin as a standby.

   ```bash
   kubectl cnpg status $DB -n $NS
   ```

8. Check the application side: the API pods must not have restarted (readiness, not
   liveness, depends on the database), and escalation must have resumed.

   ```bash
   kubectl get pods -n $NS -l app.kubernetes.io/component=api
   kubectl logs -n $NS -l app.kubernetes.io/component=worker --since=10m | grep -c "worker pass failed"
   ```

Pass criteria for part A: acknowledged writes equals the stored count, and the RESTARTS
column of the API pods did not change.

## Part B: lose the cluster, restore from S3

This deletes the database. The only copy of the data afterwards is the object store.

1. Take note of the backup identity currently in use. The restored cluster must archive
   under a new name.

   ```bash
   OLD_SERVER=$(kubectl get cluster $DB -n $NS -o jsonpath='{.spec.backup.barmanObjectStore.serverName}')
   NEW_SERVER=${OLD_SERVER%-v*}-v$(( ${OLD_SERVER##*-v} + 1 ))
   echo "$OLD_SERVER -> $NEW_SERVER"
   aws s3 ls s3://$BUCKET/cnpg/$OLD_SERVER/base/    # at least one base backup folder
   ```

2. Start the probe and let it run for at least two minutes, so there is data newer than
   the last base backup that can only come back from archived WAL.

   ```bash
   export RUN=b-$(date -u +%H%M%S)
   probe
   ```

3. Destroy the cluster and its volumes. Record the time: this is the disaster.

   ```bash
   date -u +%Y-%m-%dT%H:%M:%S.%3NZ   # record as "disaster time"
   kubectl delete cluster $DB -n $NS --wait=false
   kubectl delete pods -n $NS -l cnpg.io/cluster=$DB --grace-period=0 --force
   kubectl delete pvc -n $NS -l cnpg.io/cluster=$DB
   ```

   Deleting the pods by force matters: a graceful shutdown would archive the last WAL
   segment and make the RPO look better than it is in a real loss.

4. Restore. The same chart creates the cluster in recovery mode.

   ```bash
   date -u +%Y-%m-%dT%H:%M:%S.%3NZ   # record as "restore start"
   helm upgrade $RELEASE deploy/helm/incident-manager -n $NS --reuse-values --no-hooks \
     --set postgres.recovery.enabled=true \
     --set postgres.recovery.sourceServerName=$OLD_SERVER \
     --set postgres.backup.serverName=$NEW_SERVER
   ```

   `--no-hooks` skips the migration job. It is a pre-upgrade hook, so Helm would wait for
   it before creating the cluster, and it cannot succeed without a database. The schema
   comes back with the restored data.

   For a point-in-time restore (for example to just before a bad migration) add
   `--set-string postgres.recovery.targetTime=2026-01-31T12:00:00Z`. For this drill leave
   it out to recover as much as the archive contains.

5. Watch the recovery.

   ```bash
   kubectl get cluster $DB -n $NS -w
   kubectl get pods -n $NS -l cnpg.io/cluster=$DB    # the first pod is the recovery job
   kubectl logs -n $NS <recovery job pod> -f
   ```

   Record when the first instance becomes primary and when the cluster reports
   "Cluster in healthy state" with all three instances.

6. When the probe is back to `200` for 60 seconds, stop it and collect the numbers as in
   part A, step 6. `max(created_at)` from `stored` is the recovery point.

7. Verify that the restored cluster is itself protected again.

   ```bash
   kubectl cnpg status $DB -n $NS          # WAL archiving OK, new first recoverability point
   aws s3 ls s3://$BUCKET/cnpg/$NEW_SERVER/
   ```

8. Verify application behaviour on restored data: open incidents from before the disaster
   are on the board, and one that was unacknowledged continues escalating.

9. Keep the new values. `postgres.backup.serverName` must stay at `$NEW_SERVER` in the
   values file used for future deploys. `postgres.recovery.*` can stay set; CloudNativePG
   only reads the bootstrap section when it creates a cluster.

Pass criteria for part B: the service returns without manual steps beyond the ones above,
and the lost window (disaster time − recovery point) is not larger than `archive_timeout`
plus the upload time of one WAL segment.

## Clean up

```bash
kubectl cnpg psql $DB -n $NS -- -d incident -c \
  "delete from incidents where group_labels->>'service' like 'drill-%'"
rm probe-*.log
```

## Results

Fill in one row per run. Leave a cell empty rather than estimating it.

### Environment

| Field | Value |
|-------|-------|
| Date of drill | |
| Performed by | |
| Cluster / region | |
| Kubernetes version | |
| CloudNativePG operator version | |
| PostgreSQL image | |
| Chart version / git commit | |
| Database size at time of drill | |

### Part A: primary failure

| Measurement | Value |
|-------------|-------|
| Kill time (UTC) | |
| Old primary → new primary | |
| First failed request (UTC) | |
| First successful request after failover (UTC) | |
| **RTO** (seconds) | |
| Acknowledged writes | |
| Stored rows | |
| **RPO** (records / seconds) | |
| API pod restarts during drill | |
| Old primary rejoined as standby (yes/no, after how long) | |

### Part B: full restore from object store

| Measurement | Value |
|-------------|-------|
| Disaster time (UTC) | |
| Restore start (UTC) | |
| First instance primary (UTC) | |
| Cluster healthy with 3 instances (UTC) | |
| First successful request after restore (UTC) | |
| **RTO** (from disaster to first successful request) | |
| Of which: time until restore was started | |
| Last acknowledged write before disaster (UTC) | |
| Recovery point: newest stored row (UTC) | |
| Acknowledged writes / stored rows | |
| **RPO** (records / seconds) | |
| WAL archiving healthy under new server name (yes/no) | |

### Observations and follow-ups

| Observation | Action | Owner |
|-------------|--------|-------|
| | | |
