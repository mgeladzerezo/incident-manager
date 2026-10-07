import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import InvalidToken, Role
from app.models import User
from tests.conftest import AUDIENCE, ISSUER, T0, WEBHOOK_AUTH, WEBHOOK_TOKEN, alert, webhook

API = "/api/v1"


class TestTokenVerifier:
    def test_valid_token_yields_identity_and_roles(self, verifier, make_token):
        principal = verifier.verify(make_token("responder", "manager"))

        assert principal.subject == "kc-user-1"
        assert principal.email == "alice@example.com"
        assert principal.name == "Alice"
        assert principal.roles == {Role.RESPONDER, Role.MANAGER}

    def test_roles_unknown_to_this_application_are_dropped(self, verifier, make_token):
        principal = verifier.verify(make_token("offline_access", "responder", "uma_authorization"))

        assert principal.roles == {Role.RESPONDER}

    def test_expired_token_is_rejected(self, verifier, make_token):
        expired = make_token("admin", exp=datetime.now(UTC) - timedelta(seconds=1))

        with pytest.raises(InvalidToken):
            verifier.verify(expired)

    def test_token_from_another_issuer_is_rejected(self, verifier, make_token):
        with pytest.raises(InvalidToken):
            verifier.verify(make_token("admin", iss="https://evil.test/realms/incident"))

    def test_token_for_another_audience_is_rejected(self, verifier, make_token):
        with pytest.raises(InvalidToken):
            verifier.verify(make_token("admin", aud="some-other-client"))

    def test_token_signed_with_another_key_is_rejected(self, verifier, make_token):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        with pytest.raises(InvalidToken):
            verifier.verify(make_token("admin", key=other_key))

    def test_unsigned_token_is_rejected(self, verifier):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "x",
            "email": "x@example.com",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "realm_access": {"roles": ["admin"]},
        }
        with pytest.raises(InvalidToken):
            verifier.verify(jwt.encode(claims, key=None, algorithm="none"))

    def test_hmac_token_signed_with_the_public_key_is_rejected(self, verifier, signing_key):
        # Algorithm confusion: the public key is not a secret, so HS256 must never be accepted.
        public_pem = signing_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        header = jwt.utils.base64url_encode(b'{"alg":"HS256","typ":"JWT"}')
        payload = jwt.utils.base64url_encode(
            b'{"iss":"%s","aud":"%s","sub":"x","email":"x@example.com","exp":9999999999,'
            b'"realm_access":{"roles":["admin"]}}' % (ISSUER.encode(), AUDIENCE.encode())
        )
        signature = jwt.utils.base64url_encode(
            hmac.new(public_pem, header + b"." + payload, hashlib.sha256).digest()
        )
        forged = b".".join([header, payload, signature]).decode()

        with pytest.raises(InvalidToken):
            verifier.verify(forged)

    @pytest.mark.parametrize("claim", ["exp", "sub", "aud", "iss"])
    def test_token_missing_a_required_claim_is_rejected(self, verifier, signing_key, claim):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "x",
            "email": "x@example.com",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        }
        del claims[claim]

        with pytest.raises(InvalidToken):
            verifier.verify(jwt.encode(claims, signing_key, algorithm="RS256"))

    def test_token_without_email_is_rejected(self, verifier, make_token):
        with pytest.raises(InvalidToken, match="email"):
            verifier.verify(make_token("admin", email=""))

    def test_garbage_is_rejected(self, verifier):
        with pytest.raises(InvalidToken):
            verifier.verify("not-a-jwt")

    def test_roles_are_hierarchical(self, verifier, make_token):
        admin = verifier.verify(make_token("admin"))
        responder = verifier.verify(make_token("responder"))

        assert admin.has_role(Role.MANAGER) and admin.has_role(Role.RESPONDER)
        assert not responder.has_role(Role.MANAGER)


class TestApiAuthentication:
    def test_request_without_a_token_is_unauthorized(self, client):
        response = client.get(f"{API}/incidents")

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_request_with_an_invalid_token_is_unauthorized(self, client):
        response = client.get(f"{API}/incidents", headers={"Authorization": "Bearer nope"})

        assert response.status_code == 401

    def test_expired_token_is_unauthorized(self, client, auth):
        headers = auth("admin", exp=datetime.now(UTC) - timedelta(minutes=1))

        assert client.get(f"{API}/incidents", headers=headers).status_code == 401

    def test_authenticated_user_without_any_role_is_forbidden(self, client, auth):
        assert client.get(f"{API}/incidents", headers=auth()).status_code == 403
        assert client.get(f"{API}/incidents", headers=auth("offline_access")).status_code == 403

    def test_webhook_token_does_not_work_as_a_user_token(self, client):
        assert client.get(f"{API}/incidents", headers=WEBHOOK_AUTH).status_code == 401

    @pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
    def test_operational_endpoints_need_no_token(self, client, path):
        assert client.get(path).status_code == 200


SCHEDULE_BODY = {
    "name": "primary",
    "timezone": "UTC",
    "rotation_start": "2026-01-05T09:00:00",
    "shift_length_days": 7,
    "participant_ids": [1],
}
POLICY_BODY = {"name": "p", "levels": [{"timeout_minutes": 5, "targets": [{"user_id": 1}]}]}
USER_BODY = {"email": "new@example.com", "name": "New"}

# (method, path, body, minimum role)
PROTECTED = [
    ("GET", "/me", None, "responder"),
    ("GET", "/users", None, "responder"),
    ("POST", "/users", USER_BODY, "admin"),
    ("GET", "/incidents", None, "responder"),
    ("GET", "/schedules", None, "responder"),
    ("POST", "/schedules", SCHEDULE_BODY, "manager"),
    ("PUT", "/schedules/999", SCHEDULE_BODY, "manager"),
    ("DELETE", "/schedules/999/overrides/1", None, "manager"),
    ("GET", "/escalation-policies", None, "responder"),
    ("POST", "/escalation-policies", POLICY_BODY, "manager"),
    ("PUT", "/escalation-policies/999", POLICY_BODY, "manager"),
]
ROLES = ["responder", "manager", "admin"]


class TestRoleChecks:
    @pytest.mark.parametrize(("method", "path", "body", "minimum"), PROTECTED)
    def test_endpoint_enforces_its_minimum_role(self, client, auth, method, path, body, minimum):
        # The first request creates user 1 so the bodies above reference a real user.
        client.get(f"{API}/me", headers=auth("responder"))

        for role in ROLES:
            response = client.request(method, f"{API}{path}", json=body, headers=auth(role))
            allowed = ROLES.index(role) >= ROLES.index(minimum)
            if allowed:
                assert response.status_code not in (401, 403), (role, response.text)
            else:
                assert response.status_code == 403, (role, response.text)

    @pytest.mark.parametrize(("method", "path", "body", "minimum"), PROTECTED)
    def test_endpoint_rejects_anonymous_requests(self, client, method, path, body, minimum):
        assert client.request(method, f"{API}{path}", json=body).status_code == 401

    def test_responder_can_acknowledge_and_resolve(self, client, auth):
        client.post(f"{API}/webhooks/alertmanager", json=webhook(alert()), headers=WEBHOOK_AUTH)

        headers = auth("responder")
        assert client.post(f"{API}/incidents/1/acknowledge", headers=headers).status_code == 200
        assert client.post(f"{API}/incidents/1/resolve", headers=headers).status_code == 200

    def test_responder_can_override_only_for_themselves(self, client, auth, session):
        bob = User(email="bob@example.com", name="Bob", created_at=T0)
        session.add(bob)
        session.commit()
        client.post(
            f"{API}/schedules",
            json={**SCHEDULE_BODY, "participant_ids": [bob.id]},
            headers=auth("manager", sub="kc-manager", email="manager@example.com"),
        )
        alice = client.get(f"{API}/me", headers=auth("responder")).json()["user"]
        window = {"starts_at": "2026-03-02T18:00:00Z", "ends_at": "2026-03-03T06:00:00Z"}

        own = client.post(
            f"{API}/schedules/1/overrides",
            json={"user_id": alice["id"], **window},
            headers=auth("responder"),
        )
        for_bob = client.post(
            f"{API}/schedules/1/overrides",
            json={"user_id": bob.id, **window},
            headers=auth("responder"),
        )
        for_bob_as_manager = client.post(
            f"{API}/schedules/1/overrides",
            json={"user_id": bob.id, **window},
            headers=auth("manager", sub="kc-manager", email="manager@example.com"),
        )

        assert own.status_code == 201
        assert for_bob.status_code == 403
        assert for_bob_as_manager.status_code == 201

    def test_only_a_manager_can_publish_a_postmortem(self, client, auth):
        client.post(f"{API}/webhooks/alertmanager", json=webhook(alert()), headers=WEBHOOK_AUTH)
        url = f"{API}/incidents/1/postmortem"
        document = {"type": "doc", "content": []}

        draft = client.put(url, json={"content": document}, headers=auth("responder"))
        publish = client.put(
            url, json={"content": document, "status": "published"}, headers=auth("responder")
        )
        assert (draft.status_code, publish.status_code) == (200, 403)

        published = client.put(
            url, json={"content": document, "status": "published"}, headers=auth("manager")
        )
        edit_after = client.put(url, json={"content": document}, headers=auth("responder"))
        assert (published.status_code, edit_after.status_code) == (200, 403)

    def test_users_edit_their_own_contact_details_and_admins_edit_anyone(
        self, client, auth, session
    ):
        bob = User(email="bob@example.com", name="Bob", created_at=T0)
        session.add(bob)
        session.commit()
        me = client.get(f"{API}/me", headers=auth("responder")).json()["user"]
        change = {"telegram_chat_id": "99"}

        own = client.patch(f"{API}/users/{me['id']}", json=change, headers=auth("responder"))
        other = client.patch(f"{API}/users/{bob.id}", json=change, headers=auth("manager"))
        as_admin = client.patch(f"{API}/users/{bob.id}", json=change, headers=auth("admin"))

        assert (own.status_code, other.status_code, as_admin.status_code) == (200, 403, 200)
        assert own.json()["telegram_chat_id"] == "99"


class TestUserProvisioning:
    def test_first_login_creates_the_user_once(self, client, auth, session):
        first = client.get(f"{API}/me", headers=auth("responder", "manager")).json()
        second = client.get(f"{API}/me", headers=auth("responder", "manager")).json()

        assert first == second
        assert first["roles"] == ["manager", "responder"]
        assert first["user"]["email"] == "alice@example.com"
        assert session.query(User).count() == 1

    def test_user_precreated_by_an_admin_is_adopted_on_first_login(self, client, auth, session):
        admin = auth("admin", sub="kc-admin", email="admin@example.com")
        created = client.post(
            f"{API}/users",
            json={"email": "alice@example.com", "name": "Alice A.", "slack_user_id": "U1"},
            headers=admin,
        ).json()

        me = client.get(f"{API}/me", headers=auth("responder")).json()["user"]

        assert me["id"] == created["id"]
        assert me["slack_user_id"] == "U1"
        assert session.get(User, me["id"]).subject == "kc-user-1"


class TestWebhookAuthentication:
    URL = f"{API}/webhooks/alertmanager"

    def test_correct_token_is_accepted(self, client):
        response = client.post(self.URL, json=webhook(alert()), headers=WEBHOOK_AUTH)

        assert response.status_code == 200
        assert response.json()["incidents_opened"] == 1

    def test_missing_token_is_rejected(self, client):
        assert client.post(self.URL, json=webhook(alert())).status_code == 401

    @pytest.mark.parametrize(
        "token", ["wrong", WEBHOOK_TOKEN + "x", WEBHOOK_TOKEN[:-1], WEBHOOK_TOKEN.upper()]
    )
    def test_wrong_token_is_rejected(self, client, token):
        response = client.post(
            self.URL, json=webhook(alert()), headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    def test_basic_auth_scheme_is_rejected(self, client):
        response = client.post(
            self.URL, json=webhook(alert()), headers={"Authorization": f"Basic {WEBHOOK_TOKEN}"}
        )

        assert response.status_code == 401

    def test_user_token_is_not_a_webhook_credential(self, client, auth):
        response = client.post(self.URL, json=webhook(alert()), headers=auth("admin"))

        assert response.status_code == 401

    def test_rejected_request_creates_nothing(self, client, auth):
        client.post(self.URL, json=webhook(alert()), headers={"Authorization": "Bearer wrong"})

        assert client.get(f"{API}/incidents", headers=auth("responder")).json() == []

    def test_unset_token_rejects_everything(self, client, settings):
        settings.webhook_token = ""

        for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer x"}):
            assert client.post(self.URL, json=webhook(alert()), headers=headers).status_code == 401

    def test_malformed_payload_is_a_validation_error_not_a_crash(self, client):
        naive = alert()
        naive["startsAt"] = "2026-03-02T11:58:00"
        for body in ({"alerts": [{"status": "firing"}]}, {}, webhook(naive)):
            assert client.post(self.URL, json=body, headers=WEBHOOK_AUTH).status_code == 422
