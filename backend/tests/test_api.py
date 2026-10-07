import pytest

from tests.conftest import WEBHOOK_AUTH, alert, make_policy, make_user, webhook

API = "/api/v1"


@pytest.fixture
def responder(auth):
    return auth("responder")


@pytest.fixture
def manager(auth):
    return auth("manager")


def send_alerts(client, *alerts: dict) -> dict:
    response = client.post(
        f"{API}/webhooks/alertmanager", json=webhook(*alerts), headers=WEBHOOK_AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestIncidents:
    def test_incident_lifecycle(self, client, clock, responder):
        send_alerts(client, alert(instance="web-1"), alert(instance="web-2"))

        (summary,) = client.get(f"{API}/incidents", headers=responder).json()
        assert summary["status"] == "open"
        assert (summary["alert_count"], summary["firing_alert_count"]) == (2, 2)

        clock.advance(minutes=2)
        acknowledged = client.post(f"{API}/incidents/1/acknowledge", headers=responder).json()
        assert acknowledged["status"] == "acknowledged"
        assert acknowledged["acknowledged_by_name"] == "Alice"
        assert acknowledged["acknowledged_at"] == "2026-03-02T12:02:00Z"
        assert acknowledged["next_escalation_at"] is None

        client.post(f"{API}/incidents/1/notes", json={"text": "Rolling back."}, headers=responder)
        resolved = client.post(f"{API}/incidents/1/resolve", headers=responder).json()
        assert resolved["status"] == "resolved"
        assert resolved["resolved_by_name"] == "Alice"
        assert [(e["kind"], e["actor_name"]) for e in resolved["timeline"]] == [
            ("opened", None),
            ("escalation", None),
            ("alert", None),
            ("acknowledged", "Alice"),
            ("note", "Alice"),
            ("resolved", "Alice"),
        ]

    def test_acknowledging_twice_is_idempotent(self, client, responder):
        send_alerts(client, alert())

        first = client.post(f"{API}/incidents/1/acknowledge", headers=responder).json()
        second = client.post(f"{API}/incidents/1/acknowledge", headers=responder).json()

        assert first["acknowledged_at"] == second["acknowledged_at"]
        assert len(second["timeline"]) == len(first["timeline"])

    def test_acknowledging_a_resolved_incident_conflicts(self, client, responder):
        send_alerts(client, alert())
        send_alerts(client, alert(status="resolved"))

        assert client.post(f"{API}/incidents/1/acknowledge", headers=responder).status_code == 409

    def test_list_can_be_filtered_by_status(self, client, responder):
        send_alerts(client, alert(service="a"), alert(service="b"), alert(service="c"))
        client.post(f"{API}/incidents/2/acknowledge", headers=responder)
        send_alerts(client, alert(status="resolved", service="c"))

        def ids(status: str) -> list[int]:
            rows = client.get(f"{API}/incidents", params={"status": status}, headers=responder)
            return [row["id"] for row in rows.json()]

        assert (ids("open"), ids("acknowledged"), ids("resolved")) == ([1], [2], [3])
        assert client.get(f"{API}/incidents?status=bogus", headers=responder).status_code == 422

    def test_detail_shows_alerts_and_pages(self, client, session, responder):
        oncall, backup = make_user(session, "Oncall"), make_user(session, "Backup")
        make_policy(session, [(5, [oncall]), (10, [backup])])
        session.commit()
        send_alerts(client, alert(service="search"))

        detail = client.get(f"{API}/incidents/1", headers=responder).json()

        assert detail["policy_name"] == "default"
        assert detail["next_escalation_at"] == "2026-03-02T12:05:00Z"
        assert detail["alerts"][0]["labels"]["service"] == "search"
        (page,) = detail["pages"]
        assert (page["level"], page["user_name"], page["channel"], page["status"]) == (
            1,
            "Oncall",
            "slack",
            "pending",
        )

    def test_unknown_incident_is_not_found(self, client, responder):
        assert client.get(f"{API}/incidents/42", headers=responder).status_code == 404
        assert client.post(f"{API}/incidents/42/resolve", headers=responder).status_code == 404

    def test_postmortem_round_trip(self, client, responder):
        send_alerts(client, alert())
        url = f"{API}/incidents/1/postmortem"
        document = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Root cause"}]}],
        }

        assert client.get(url, headers=responder).status_code == 404
        saved = client.put(url, json={"content": document}, headers=responder).json()
        loaded = client.get(url, headers=responder).json()

        assert saved == loaded
        assert loaded["content"] == document
        assert (loaded["status"], loaded["updated_by_name"]) == ("draft", "Alice")


class TestSchedules:
    @pytest.fixture
    def user_ids(self, session) -> list[int]:
        users = [make_user(session, name) for name in ("Ana", "Ben")]
        session.commit()
        return [user.id for user in users]

    @pytest.fixture
    def schedule(self, client, manager, user_ids) -> dict:
        response = client.post(
            f"{API}/schedules",
            json={
                "name": "platform",
                "timezone": "Europe/Zagreb",
                "rotation_start": "2026-01-05T09:00:00",
                "shift_length_days": 7,
                "participant_ids": user_ids,
            },
            headers=manager,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_create_and_read_back(self, client, responder, schedule):
        loaded = client.get(f"{API}/schedules/{schedule['id']}", headers=responder).json()

        assert loaded == schedule
        assert [user["name"] for user in loaded["users"]] == ["Ana", "Ben"]
        assert loaded["rotation_start"] == "2026-01-05T09:00:00"

    def test_on_call_now_and_at_a_given_time(self, client, responder, schedule):
        url = f"{API}/schedules/{schedule['id']}/on-call"

        # The fake clock reads 2026-03-02 12:00 UTC: shift 8, so Ana.
        now = client.get(url, headers=responder).json()
        later = client.get(
            url, params={"at": "2026-03-09T09:00:00+01:00"}, headers=responder
        ).json()
        before_start = client.get(
            url, params={"at": "2025-01-01T00:00:00Z"}, headers=responder
        ).json()

        assert (now["user"]["name"], now["source"]) == ("Ana", "rotation")
        assert later["user"]["name"] == "Ben"
        assert before_start == {"user": None, "source": None}

    def test_shifts_include_overrides(self, client, responder, manager, schedule, user_ids):
        created = client.post(
            f"{API}/schedules/{schedule['id']}/overrides",
            json={
                "user_id": user_ids[1],
                "starts_at": "2026-03-03T00:00:00Z",
                "ends_at": "2026-03-04T00:00:00Z",
            },
            headers=manager,
        )
        assert created.status_code == 201

        def shifts() -> list[tuple[str, str, str]]:
            rows = client.get(
                f"{API}/schedules/{schedule['id']}/shifts",
                params={"start": "2026-03-02T00:00:00Z", "end": "2026-03-10T00:00:00Z"},
                headers=responder,
            ).json()
            return [(row["user"]["name"], row["source"], row["starts_at"]) for row in rows]

        assert shifts() == [
            ("Ben", "rotation", "2026-03-02T00:00:00Z"),
            ("Ana", "rotation", "2026-03-02T08:00:00Z"),
            ("Ben", "override", "2026-03-03T00:00:00Z"),
            ("Ana", "rotation", "2026-03-04T00:00:00Z"),
            ("Ben", "rotation", "2026-03-09T08:00:00Z"),
        ]

        deleted = client.delete(
            f"{API}/schedules/{schedule['id']}/overrides/{created.json()['id']}", headers=manager
        )
        assert deleted.status_code == 204
        assert [source for _, source, _ in shifts()] == ["rotation"] * 3

    def test_update_replaces_participants_in_order(self, client, manager, schedule, user_ids):
        body = {
            "name": "platform",
            "timezone": "UTC",
            "rotation_start": "2026-02-02T08:00:00",
            "shift_length_days": 1,
            "participant_ids": list(reversed(user_ids)),
        }

        updated = client.put(f"{API}/schedules/{schedule['id']}", json=body, headers=manager)

        assert updated.status_code == 200, updated.text
        assert [user["name"] for user in updated.json()["users"]] == ["Ben", "Ana"]

    @pytest.mark.parametrize(
        "change",
        [
            {"timezone": "Mars/Olympus_Mons"},
            {"rotation_start": "2026-01-05T09:00:00Z"},
            {"shift_length_days": 0},
            {"participant_ids": []},
            {"participant_ids": [9999]},
        ],
    )
    def test_invalid_schedule_is_rejected(self, client, manager, user_ids, change):
        body = {
            "name": "x",
            "timezone": "UTC",
            "rotation_start": "2026-01-05T09:00:00",
            "shift_length_days": 7,
            "participant_ids": user_ids,
            **change,
        }

        assert client.post(f"{API}/schedules", json=body, headers=manager).status_code == 422

    def test_duplicate_schedule_name_conflicts(self, client, manager, schedule, user_ids):
        body = {
            "name": "platform",
            "timezone": "UTC",
            "rotation_start": "2026-01-05T09:00:00",
            "shift_length_days": 7,
            "participant_ids": user_ids,
        }

        assert client.post(f"{API}/schedules", json=body, headers=manager).status_code == 409

    def test_shift_query_needs_offsets_and_a_sane_range(self, client, responder, schedule):
        url = f"{API}/schedules/{schedule['id']}/shifts"

        def status(start: str, end: str) -> int:
            return client.get(
                url, params={"start": start, "end": end}, headers=responder
            ).status_code

        assert status("2026-03-02T00:00:00", "2026-03-10T00:00:00") == 422
        assert status("2026-03-10T00:00:00Z", "2026-03-02T00:00:00Z") == 422
        assert status("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z") == 422

    def test_override_must_end_after_it_starts(self, client, manager, schedule, user_ids):
        response = client.post(
            f"{API}/schedules/{schedule['id']}/overrides",
            json={
                "user_id": user_ids[0],
                "starts_at": "2026-03-04T00:00:00Z",
                "ends_at": "2026-03-03T00:00:00Z",
            },
            headers=manager,
        )

        assert response.status_code == 422


class TestEscalationPolicies:
    def test_create_policy_with_schedule_and_user_targets(self, client, session, manager):
        user = make_user(session, "Ana")
        session.commit()
        schedule = client.post(
            f"{API}/schedules",
            json={
                "name": "platform",
                "timezone": "UTC",
                "rotation_start": "2026-01-05T09:00:00",
                "shift_length_days": 7,
                "participant_ids": [user.id],
            },
            headers=manager,
        ).json()

        response = client.post(
            f"{API}/escalation-policies",
            json={
                "name": "platform",
                "is_default": True,
                "levels": [
                    {"timeout_minutes": 5, "targets": [{"schedule_id": schedule["id"]}]},
                    {"timeout_minutes": 15, "targets": [{"user_id": user.id}]},
                ],
            },
            headers=manager,
        )

        assert response.status_code == 201, response.text
        assert response.json()["levels"] == [
            {
                "position": 1,
                "timeout_minutes": 5,
                "targets": [
                    {
                        "schedule_id": schedule["id"],
                        "schedule_name": "platform",
                        "user_id": None,
                        "user_name": None,
                    }
                ],
            },
            {
                "position": 2,
                "timeout_minutes": 15,
                "targets": [
                    {
                        "schedule_id": None,
                        "schedule_name": None,
                        "user_id": user.id,
                        "user_name": "Ana",
                    }
                ],
            },
        ]

    def test_only_one_policy_is_the_default(self, client, session, manager):
        user = make_user(session, "Ana")
        session.commit()

        def body(name: str) -> dict:
            return {
                "name": name,
                "is_default": True,
                "levels": [{"timeout_minutes": 5, "targets": [{"user_id": user.id}]}],
            }

        client.post(f"{API}/escalation-policies", json=body("first"), headers=manager)
        client.post(f"{API}/escalation-policies", json=body("second"), headers=manager)

        policies = client.get(f"{API}/escalation-policies", headers=manager).json()
        assert {p["name"]: p["is_default"] for p in policies} == {"first": False, "second": True}

    def test_update_replaces_levels(self, client, session, manager):
        user = make_user(session, "Ana")
        session.commit()
        level = {"timeout_minutes": 5, "targets": [{"user_id": user.id}]}
        created = client.post(
            f"{API}/escalation-policies",
            json={"name": "p", "levels": [level, level]},
            headers=manager,
        ).json()

        updated = client.put(
            f"{API}/escalation-policies/{created['id']}",
            json={"name": "p", "levels": [{**level, "timeout_minutes": 30}]},
            headers=manager,
        )

        assert updated.status_code == 200, updated.text
        assert [(lv["position"], lv["timeout_minutes"]) for lv in updated.json()["levels"]] == [
            (1, 30)
        ]

    @pytest.mark.parametrize(
        "levels",
        [
            [],
            [{"timeout_minutes": 5, "targets": []}],
            [{"timeout_minutes": 0, "targets": [{"user_id": 1}]}],
            [{"timeout_minutes": 5, "targets": [{}]}],
            [{"timeout_minutes": 5, "targets": [{"user_id": 1, "schedule_id": 1}]}],
            [{"timeout_minutes": 5, "targets": [{"user_id": 9999}]}],
            [{"timeout_minutes": 5, "targets": [{"schedule_id": 9999}]}],
        ],
    )
    def test_invalid_policy_is_rejected(self, client, manager, levels):
        response = client.post(
            f"{API}/escalation-policies", json={"name": "p", "levels": levels}, headers=manager
        )

        assert response.status_code == 422


def test_metrics_expose_application_counters(client):
    send_alerts(client, alert())

    body = client.get("/metrics").text

    assert 'incident_manager_alerts_received_total{outcome="added"}' in body
    assert 'incident_manager_incidents_opened_total{severity="critical"}' in body
    assert 'route="/api/v1/webhooks/alertmanager"' in body
