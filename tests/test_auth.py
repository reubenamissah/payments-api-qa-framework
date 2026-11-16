import pytest
from jsonschema import validate

from tests.conftest import load_schema

PROTECTED = [
    ("POST", "/accounts"),
    ("GET", "/accounts/acc_000000000000"),
    ("POST", "/transfers"),
    ("GET", "/transfers/trf_000000000000"),
]


@pytest.mark.smoke
def test_valid_credentials_return_a_bearer_token(anon):
    response = anon.request_token()
    assert response.status_code == 200
    validate(response.json(), load_schema("token"))


def test_each_token_request_issues_a_unique_token(anon):
    first = anon.request_token().json()["access_token"]
    second = anon.request_token().json()["access_token"]
    assert first != second


@pytest.mark.negative
@pytest.mark.parametrize("client_id, client_secret", [
    ("qa-client", "wrong-secret"),
    ("wrong-client", "qa-secret"),
    ("", ""),
    ("QA-CLIENT", "qa-secret"),  # credentials are case sensitive
])
def test_bad_credentials_are_rejected(anon, client_id, client_secret):
    response = anon.request_token(client_id, client_secret)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.negative
@pytest.mark.parametrize("body", [{}, {"client_id": "qa-client"}, {"client_secret": "qa-secret"}])
def test_missing_credential_fields_return_validation_error(anon, body):
    response = anon.http.post("/auth/token", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.negative
@pytest.mark.parametrize("method, path", PROTECTED)
def test_protected_endpoints_require_a_token(anon, method, path):
    response = anon.http.request(method, path)
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.negative
@pytest.mark.parametrize("header", [
    "Bearer not-a-real-token",
    "Basic dXNlcjpwYXNz",
    "Bearer",
    "token abc",
])
def test_malformed_or_unknown_authorization_headers_are_rejected(anon, header):
    response = anon.http.get("/accounts/acc_000000000000", headers={"Authorization": header})
    assert response.status_code == 401
