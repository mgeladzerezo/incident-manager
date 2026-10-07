"""OIDC bearer-token verification and role checks.

The API never talks to Keycloak during a request beyond fetching (and caching) its signing
keys. Roles come from the `realm_access.roles` claim Keycloak puts in access tokens.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import jwt

ALGORITHMS = ["RS256"]


class Role(StrEnum):
    RESPONDER = "responder"
    MANAGER = "manager"
    ADMIN = "admin"


_RANK = {Role.RESPONDER: 1, Role.MANAGER: 2, Role.ADMIN: 3}


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str
    name: str
    roles: frozenset[Role]

    def has_role(self, required: Role) -> bool:
        """Roles are ordered: an admin can do what a manager can, and so on."""
        return any(_RANK[role] >= _RANK[required] for role in self.roles)


class SigningKeyProvider(Protocol):
    def signing_key(self, token: str) -> Any:
        """Public key matching the token's `kid` header."""


class JwksKeyProvider:
    def __init__(self, jwks_url: str) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)

    def signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, keys: SigningKeyProvider) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = keys

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._keys.signing_key(token),
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(str(exc)) from exc

        email = claims.get("email")
        if not email:
            raise InvalidToken("token has no email claim")
        return Principal(
            subject=claims["sub"],
            email=email,
            name=claims.get("name") or claims.get("preferred_username") or email,
            roles=_roles_from(claims),
        )


def _roles_from(claims: dict[str, Any]) -> frozenset[Role]:
    granted = claims.get("realm_access", {}).get("roles", [])
    known = {role.value for role in Role}
    return frozenset(Role(name) for name in granted if name in known)
