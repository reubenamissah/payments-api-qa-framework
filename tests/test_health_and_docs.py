import pytest

pytestmark = [pytest.mark.smoke]


def test_health_endpoint_is_up(anon):
    response = anon.http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_carries_a_request_id_for_traceability(anon):
    response = anon.http.get("/health")
    assert response.headers.get("X-Request-Id")


def test_caller_supplied_request_id_is_echoed_back(anon):
    response = anon.http.get("/health", headers={"X-Request-Id": "trace-me-123"})
    assert response.headers["X-Request-Id"] == "trace-me-123"


def test_openapi_document_lists_the_public_endpoints(anon):
    spec = anon.http.get("/openapi.json").json()
    assert {"/health", "/auth/token", "/accounts", "/accounts/{account_id}", "/transfers",
            "/transfers/{transfer_id}"} <= set(spec["paths"])


@pytest.mark.negative
def test_unknown_route_returns_the_standard_error_envelope(anon):
    response = anon.http.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
