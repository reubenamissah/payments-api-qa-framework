import pytest
from jsonschema import validate

from tests.conftest import load_schema


@pytest.mark.smoke
def test_create_account_returns_201_and_matches_contract(api):
    response = api.create_account(owner_name="Ada Lovelace", currency="GHS", initial_balance=5_000)
    assert response.status_code == 201
    body = response.json()
    validate(body, load_schema("account"))
    assert (body["owner_name"], body["currency"], body["balance"]) == ("Ada Lovelace", "GHS", 5_000)


@pytest.mark.regression
def test_created_account_can_be_fetched_with_same_data(api):
    created = api.new_account(owner_name="Fetch Me", initial_balance=250)
    fetched = api.get_account(created["id"])
    assert fetched.status_code == 200
    assert fetched.json() == created


@pytest.mark.regression
def test_initial_balance_defaults_to_zero(api):
    response = api.http.post("/accounts", json={"owner_name": "Zero", "currency": "USD"},
                             headers=api.headers())
    assert response.status_code == 201
    assert response.json()["balance"] == 0


@pytest.mark.regression
@pytest.mark.parametrize("owner_name, balance", [
    ("A", 0),                       # shortest name, lowest balance
    ("N" * 100, 1_000_000_000),     # longest name, highest balance
])
def test_boundary_values_are_accepted(api, owner_name, balance):
    response = api.create_account(owner_name=owner_name, initial_balance=balance)
    assert response.status_code == 201


@pytest.mark.negative
@pytest.mark.parametrize("override", [
    {"owner_name": ""},
    {"owner_name": "N" * 101},
    {"currency": "EUR"},
    {"currency": "ngn"},
    {"initial_balance": -1},
    {"initial_balance": 1_000_000_001},
    {"initial_balance": "500"},
    {"initial_balance": 10.5},
    {"initial_balance": True},
    {"owner_name": None},
    {"unexpected_field": "x"},
], ids=lambda o: str(o)[:40])
def test_invalid_account_payloads_are_rejected(api, override):
    response = api.create_account(**override)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.negative
def test_missing_required_field_is_rejected(api):
    response = api.http.post("/accounts", json={"currency": "NGN"}, headers=api.headers())
    assert response.status_code == 422
    fields = [d["field"] for d in response.json()["error"]["details"]]
    assert "owner_name" in fields


@pytest.mark.negative
def test_unknown_account_returns_404(api):
    response = api.get_account("acc_doesnotexist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


@pytest.mark.negative
def test_sql_injection_style_id_is_treated_as_plain_text(api):
    response = api.get_account("' OR '1'='1")
    assert response.status_code == 404
