import pytest
from jsonschema import validate

from tests.conftest import load_schema


@pytest.mark.smoke
def test_successful_transfer_moves_money_and_matches_contract(api, funded_pair):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], 2_500, narration="Rent")
    assert response.status_code == 201
    body = response.json()
    validate(body, load_schema("transfer"))
    assert body["status"] == "COMPLETED"
    assert body["narration"] == "Rent"
    assert api.balance(source["id"]) == 7_500
    assert api.balance(destination["id"]) == 2_500


@pytest.mark.regression
def test_transfer_can_be_fetched_after_creation(api, funded_pair):
    source, destination = funded_pair
    created = api.transfer(source["id"], destination["id"], 100).json()
    fetched = api.get_transfer(created["id"])
    assert fetched.status_code == 200
    assert fetched.json() == created


@pytest.mark.regression
def test_several_transfers_keep_balances_consistent(api, funded_pair):
    source, destination = funded_pair
    for amount in (1_000, 2_000, 3_000):
        assert api.transfer(source["id"], destination["id"], amount).status_code == 201
    assert api.balance(source["id"]) == 4_000
    assert api.balance(destination["id"]) == 6_000


@pytest.mark.regression
def test_transferring_the_entire_balance_leaves_zero(api, funded_pair):
    source, destination = funded_pair
    assert api.transfer(source["id"], destination["id"], 10_000).status_code == 201
    assert api.balance(source["id"]) == 0


@pytest.mark.regression
@pytest.mark.parametrize("amount", [1, 10_000_000])
def test_amount_boundaries_are_accepted(api, amount):
    source = api.new_account(initial_balance=10_000_000)
    destination = api.new_account()
    assert api.transfer(source["id"], destination["id"], amount).status_code == 201


@pytest.mark.regression
@pytest.mark.parametrize("length, expected", [(140, 201), (141, 422)])
def test_narration_length_boundary(api, funded_pair, length, expected):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], 10, narration="x" * length)
    assert response.status_code == expected


@pytest.mark.negative
@pytest.mark.parametrize("amount", [0, -1, -500, 10_000_001, "100", 1.5, True, None])
def test_invalid_amounts_are_rejected_and_balances_untouched(api, funded_pair, amount):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], amount)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.balance(source["id"]) == 10_000
    assert api.balance(destination["id"]) == 0


@pytest.mark.negative
def test_insufficient_funds_is_rejected_and_nothing_moves(api, funded_pair):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], 10_001)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert api.balance(source["id"]) == 10_000
    assert api.balance(destination["id"]) == 0


@pytest.mark.negative
def test_transfer_to_the_same_account_is_rejected(api, funded_pair):
    source, _ = funded_pair
    response = api.transfer(source["id"], source["id"], 100)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SAME_ACCOUNT"


@pytest.mark.negative
@pytest.mark.parametrize("missing", ["source", "destination"])
def test_unknown_accounts_return_404(api, funded_pair, missing):
    source, destination = funded_pair
    src = "acc_unknown00000" if missing == "source" else source["id"]
    dst = "acc_unknown00000" if missing == "destination" else destination["id"]
    response = api.transfer(src, dst, 100)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


@pytest.mark.negative
def test_currency_mismatch_between_accounts_is_rejected(api):
    ngn = api.new_account(currency="NGN", initial_balance=1_000)
    usd = api.new_account(currency="USD")
    response = api.transfer(ngn["id"], usd["id"], 100, currency="NGN")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"


@pytest.mark.negative
def test_transfer_currency_must_match_the_accounts(api, funded_pair):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], 100, currency="USD")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"


@pytest.mark.negative
@pytest.mark.parametrize("key, code", [
    ("short", "INVALID_IDEMPOTENCY_KEY"),
    ("k" * 65, "INVALID_IDEMPOTENCY_KEY"),
])
def test_idempotency_key_length_is_enforced(api, funded_pair, key, code):
    source, destination = funded_pair
    response = api.transfer(source["id"], destination["id"], 100, key=key)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


@pytest.mark.negative
def test_missing_idempotency_key_is_rejected(api, funded_pair):
    source, destination = funded_pair
    response = api.http.post("/transfers", headers=api.headers(), json={
        "source_account_id": source["id"], "destination_account_id": destination["id"],
        "amount": 100, "currency": "NGN"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"


@pytest.mark.negative
def test_unknown_transfer_returns_404(api):
    response = api.get_transfer("trf_doesnotexist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRANSFER_NOT_FOUND"
