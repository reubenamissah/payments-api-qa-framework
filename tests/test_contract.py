"""Every error the API can return must use the same envelope (consumers depend on it)."""
import pytest
from jsonschema import validate

from tests.conftest import load_schema

pytestmark = pytest.mark.contract


def _trigger_errors(api, anon, pair):
    source, destination = pair
    return {
        "401 no token": anon.http.get("/accounts/acc_x"),
        "401 bad credentials": anon.request_token("bad", "bad"),
        "404 account": api.get_account("acc_missing"),
        "404 transfer": api.get_transfer("trf_missing"),
        "409 idempotency": _conflict(api, source, destination),
        "422 validation": api.create_account(currency="XXX"),
        "422 business rule": api.transfer(source["id"], destination["id"], 99_999_99),
        "400 header": api.transfer(source["id"], destination["id"], 1, key="short"),
    }


def _conflict(api, source, destination):
    api.transfer(source["id"], destination["id"], 1, key="conflict-key-1")
    return api.transfer(source["id"], destination["id"], 2, key="conflict-key-1")


def test_all_error_responses_follow_the_error_schema(api, anon, funded_pair):
    schema = load_schema("error")
    for name, response in _trigger_errors(api, anon, funded_pair).items():
        assert response.status_code >= 400, name
        assert response.headers["content-type"].startswith("application/json"), name
        validate(response.json(), schema)


def test_validation_errors_name_the_offending_field(api):
    response = api.create_account(owner_name="", currency="XXX")
    fields = {d["field"] for d in response.json()["error"]["details"]}
    assert fields == {"owner_name", "currency"}


def test_responses_are_json_with_utf8_content_type(api):
    response = api.create_account(owner_name="Chiamaka Ọkọrọ")
    assert response.status_code == 201
    assert response.json()["owner_name"] == "Chiamaka Ọkọrọ"
