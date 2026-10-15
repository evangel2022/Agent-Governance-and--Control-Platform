"""OIDC access-token verification (FR-002, FR-003).

Verifies issuer, audience and expiry against a JWKS document, then projects the
token into the small Principal the application needs. A token that is missing
an organisation claim is rejected rather than defaulted, because an unscoped
principal would defeat tenant isolation (FR-036).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jose import jwk, jwt
from jose.exceptions import JWTError


class TokenError(Exception):
    """Raised when an access token cannot be trusted."""


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    subject: str
    user_id: str
    organisation_id: str
    roles: frozenset[str]
    display_name: str | None = None


def _roles_from_claims(claims: Mapping[str, Any]) -> frozenset[str]:
    direct = claims.get("roles")
    if isinstance(direct, list) and direct:
        return frozenset(str(role) for role in direct)
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, Mapping):
        nested = realm_access.get("roles")
        if isinstance(nested, list):
            return frozenset(str(role) for role in nested)
    return frozenset()


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Project verified claims into a Principal.

    Raises:
        TokenError: when the token carries no subject or no organisation claim.
    """
    subject = claims.get("sub")
    if not subject:
        raise TokenError("token has no subject")
    organisation = claims.get("org") or claims.get("organisation_id")
    if not organisation:
        raise TokenError("token carries no organisation claim")
    display_name = claims.get("name") or claims.get("preferred_username")
    return Principal(
        subject=str(subject),
        user_id=str(subject),
        organisation_id=str(organisation),
        roles=_roles_from_claims(claims),
        display_name=str(display_name) if display_name else None,
    )


class OidcVerifier:
    """Verifies RS256 access tokens against a fixed set of keys."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        keys: Mapping[str, Any],
        algorithms: Sequence[str] = ("RS256",),
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = dict(keys)
        self._algorithms = tuple(algorithms)

    @classmethod
    def from_jwks(
        cls,
        *,
        issuer: str,
        audience: str,
        jwks: Mapping[str, Any],
        algorithms: Sequence[str] = ("RS256",),
    ) -> OidcVerifier:
        """Build a verifier from a JWKS document."""
        keys: dict[str, Any] = {}
        for entry in jwks.get("keys", []):
            if not isinstance(entry, Mapping):
                continue
            kid = entry.get("kid")
            if not kid:
                continue
            algorithm = str(entry.get("alg") or "RS256")
            keys[str(kid)] = jwk.construct(dict(entry), algorithm=algorithm)
        return cls(issuer=issuer, audience=audience, keys=keys, algorithms=algorithms)

    @property
    def key_ids(self) -> Iterable[str]:
        return self._keys.keys()

    def _select_key(self, kid: str | None) -> Any:
        if kid is not None:
            key = self._keys.get(kid)
            if key is None:
                raise TokenError(f"token signed by unknown key id {kid!r}")
            return key
        if len(self._keys) == 1:
            return next(iter(self._keys.values()))
        raise TokenError("token has no key id and the key set is ambiguous")

    def verify(self, token: str) -> Principal:
        """Verify a token and return the principal it represents.

        Raises:
            TokenError: for a malformed, expired, mis-issued or mis-audienced
                token, or a token whose key is unknown.
        """
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise TokenError("malformed token") from exc

        key = self._select_key(header.get("kid"))

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "require_exp": True,
                    "require_iat": True,
                },
            )
        except JWTError as exc:
            raise TokenError(str(exc)) from exc

        return principal_from_claims(claims)
