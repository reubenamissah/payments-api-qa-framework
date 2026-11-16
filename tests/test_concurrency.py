from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.concurrency


def test_parallel_transfers_never_overdraw_the_source_account(api):
    """20 simultaneous 100-unit transfers against a 1,000 balance: exactly 10 may succeed."""
    source = api.new_account(initial_balance=1_000)
    destination = api.new_account()

    def send(_):
        return api.transfer(source["id"], destination["id"], 100)

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(send, range(20)))

    succeeded = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 422]
    assert len(succeeded) == 10
    assert len(rejected) == 10
    assert {r.json()["error"]["code"] for r in rejected} == {"INSUFFICIENT_FUNDS"}
    assert api.balance(source["id"]) == 0
    assert api.balance(destination["id"]) == 1_000


def test_opposite_direction_transfers_conserve_total_money(api):
    a = api.new_account(initial_balance=5_000)
    b = api.new_account(initial_balance=5_000)

    def send(i):
        source, dest = (a, b) if i % 2 == 0 else (b, a)
        return api.transfer(source["id"], dest["id"], 50)

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(send, range(20)))

    assert all(r.status_code == 201 for r in responses)
    assert api.balance(a["id"]) + api.balance(b["id"]) == 10_000
