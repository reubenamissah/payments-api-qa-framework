import time

import pytest

pytestmark = pytest.mark.ratelimit


def _prepare(api):
    return api.new_account(initial_balance=1_000_000), api.new_account()


def test_rate_limit_headers_report_remaining_quota(api):
    source, destination = _prepare(api)
    first = api.transfer(source["id"], destination["id"], 1)
    second = api.transfer(source["id"], destination["id"], 1)
    limit = int(first.headers["X-RateLimit-Limit"])
    assert int(first.headers["X-RateLimit-Remaining"]) == limit - 1
    assert int(second.headers["X-RateLimit-Remaining"]) == limit - 2


@pytest.mark.negative
def test_requests_over_the_limit_get_429_with_retry_after(api):
    source, destination = _prepare(api)
    limit = int(api.transfer(source["id"], destination["id"], 1).headers["X-RateLimit-Limit"])

    for _ in range(limit - 1):
        assert api.transfer(source["id"], destination["id"], 1).status_code == 201

    blocked = api.transfer(source["id"], destination["id"], 1)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_is_applied_per_token_not_globally(base_url, api):
    from tests.api_client import PaymentsAPI

    source, destination = _prepare(api)
    limit = int(api.transfer(source["id"], destination["id"], 1).headers["X-RateLimit-Limit"])
    for _ in range(limit):
        api.transfer(source["id"], destination["id"], 1)
    assert api.transfer(source["id"], destination["id"], 1).status_code == 429

    other = PaymentsAPI(base_url).authenticate()
    try:
        assert other.transfer(source["id"], destination["id"], 1).status_code == 201
    finally:
        other.close()


@pytest.mark.slow
def test_quota_resets_after_the_window(api):
    source, destination = _prepare(api)
    limit = int(api.transfer(source["id"], destination["id"], 1).headers["X-RateLimit-Limit"])
    for _ in range(limit):
        api.transfer(source["id"], destination["id"], 1)
    blocked = api.transfer(source["id"], destination["id"], 1)
    assert blocked.status_code == 429

    retry_after = int(blocked.headers["Retry-After"])
    if retry_after > 15:
        pytest.skip("Window is too long to wait for in a test run")
    time.sleep(retry_after + 0.5)
    assert api.transfer(source["id"], destination["id"], 1).status_code == 201
