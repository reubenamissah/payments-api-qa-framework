import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.idempotency


def test_replayed_request_returns_the_original_transfer_without_moving_money_twice(api, funded_pair):
    source, destination = funded_pair
    key = uuid.uuid4().hex
    first = api.transfer(source["id"], destination["id"], 1_000, key=key)
    replay = api.transfer(source["id"], destination["id"], 1_000, key=key)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.headers.get("Idempotent-Replay") == "true"
    assert replay.json() == first.json()
    assert api.balance(source["id"]) == 9_000
    assert api.balance(destination["id"]) == 1_000


@pytest.mark.negative
@pytest.mark.parametrize("change", [{"amount": 2_000}, {"narration": "different"}])
def test_reusing_a_key_with_a_different_payload_is_a_conflict(api, funded_pair, change):
    source, destination = funded_pair
    key = uuid.uuid4().hex
    api.transfer(source["id"], destination["id"], 1_000, key=key)
    params = {"amount": 1_000, **change}
    conflict = api.transfer(source["id"], destination["id"], params.pop("amount"), key=key, **params)

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert api.balance(source["id"]) == 9_000


def test_different_keys_create_independent_transfers(api, funded_pair):
    source, destination = funded_pair
    first = api.transfer(source["id"], destination["id"], 500).json()
    second = api.transfer(source["id"], destination["id"], 500).json()
    assert first["id"] != second["id"]
    assert api.balance(destination["id"]) == 1_000


@pytest.mark.concurrency
def test_parallel_duplicate_requests_debit_exactly_once(api, funded_pair):
    """Simulates a client retrying aggressively (double-click / network retry)."""
    source, destination = funded_pair
    key = uuid.uuid4().hex

    def send(_):
        return api.transfer(source["id"], destination["id"], 1_000, key=key)

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(send, range(10)))

    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(201) == 1
    assert statuses.count(200) == 9
    assert len({r.json()["id"] for r in responses}) == 1
    assert api.balance(source["id"]) == 9_000
    assert api.balance(destination["id"]) == 1_000
