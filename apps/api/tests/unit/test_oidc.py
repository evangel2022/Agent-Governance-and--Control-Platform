"""Unit tests for OIDC token verification (T023).

Tokens are signed with a real RSA key generated for the test, and verified
against a real JWKS document. Nothing here mocks the verification path.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from gov.api.interface.security.oidc import (
    OidcVerifier,
    Principal,
    TokenError,
    principal_from_claims,
)

ISSUER = "https://issuer.example/realms/gov"
AUDIENCE = "gov-api"
KID = "test-key-1"


def _b64u(value: int, length: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).decode("ascii").rstrip("=")


@pytest.fixture(scope="module")
def signing_material() -> dict[str, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64u(numbers.n, 256),
        "e": _b64u(numbers.e, 3),
    }
    return {"private_pem": private_pem, "jwks": {"keys": [jwk]}}


@pytest.fixture
def verifier(signing_material: dict[str, Any]) -> OidcVerifier:
    return OidcVerifier.from_jwks(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks=signing_material["jwks"],
    )


def _token(signing_material: dict[str, Any], **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "user-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "org": "org-1",
        "roles": ["auditor"],
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        signing_material["private_pem"],
        algorithm="RS256",
        headers={"kid": KID},
    )


def test_valid_token_is_accepted(verifier: OidcVerifier, signing_material: dict[str, Any]) -> None:
    principal = verifier.verify(_token(signing_material))
    assert principal == Principal(
        subject="user-1",
        user_id="user-1",
        organisation_id="org-1",
        roles=frozenset({"auditor"}),
    )


def test_expired_token_is_rejected(
    verifier: OidcVerifier, signing_material: dict[str, Any]
) -> None:
    now = int(time.time())
    token = _token(signing_material, iat=now - 600, exp=now - 60)
    with pytest.raises(TokenError):
        verifier.verify(token)


def test_wrong_audience_is_rejected(
    verifier: OidcVerifier, signing_material: dict[str, Any]
) -> None:
    with pytest.raises(TokenError):
        verifier.verify(_token(signing_material, aud="some-other-api"))


def test_wrong_issuer_is_rejected(verifier: OidcVerifier, signing_material: dict[str, Any]) -> None:
    with pytest.raises(TokenError):
        verifier.verify(_token(signing_material, iss="https://evil.example/realms/gov"))


def test_token_without_organisation_is_rejected(
    verifier: OidcVerifier, signing_material: dict[str, Any]
) -> None:
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode(
        claims,
        signing_material["private_pem"],
        algorithm="RS256",
        headers={"kid": KID},
    )
    with pytest.raises(TokenError, match="organisation"):
        verifier.verify(token)


def test_token_without_expiry_is_rejected(
    verifier: OidcVerifier, signing_material: dict[str, Any]
) -> None:
    now = int(time.time())
    claims = {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "org": "org-1"}
    token = jwt.encode(
        claims,
        signing_material["private_pem"],
        algorithm="RS256",
        headers={"kid": KID},
    )
    with pytest.raises(TokenError):
        verifier.verify(token)


def test_token_from_an_unknown_key_is_rejected(
    verifier: OidcVerifier, signing_material: dict[str, Any]
) -> None:
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "org": "org-1",
    }
    token = jwt.encode(
        claims,
        signing_material["private_pem"],
        algorithm="RS256",
        headers={"kid": "an-unknown-key"},
    )
    with pytest.raises(TokenError, match="unknown key id"):
        verifier.verify(token)


@pytest.mark.parametrize("token", ["", "not.a.token", "a.b.c"])
def test_malformed_tokens_are_rejected(verifier: OidcVerifier, token: str) -> None:
    with pytest.raises(TokenError):
        verifier.verify(token)


def test_keycloak_realm_access_roles_are_read() -> None:
    principal = principal_from_claims(
        {
            "sub": "user-9",
            "org": "org-2",
            "realm_access": {"roles": ["business_approver", "offline_access"]},
        }
    )
    assert principal.roles == frozenset({"business_approver", "offline_access"})
    assert principal.organisation_id == "org-2"


def test_claims_without_roles_yield_no_roles() -> None:
    principal = principal_from_claims({"sub": "user-9", "org": "org-2"})
    assert principal.roles == frozenset()


def test_verifier_exposes_its_key_ids(verifier: OidcVerifier) -> None:
    assert list(verifier.key_ids) == [KID]


def test_jwks_without_keys_produces_an_empty_key_set() -> None:
    built = OidcVerifier.from_jwks(issuer=ISSUER, audience=AUDIENCE, jwks={"keys": []})
    assert list(built.key_ids) == []
    with pytest.raises(TokenError):
        built.verify("a.b.c")
