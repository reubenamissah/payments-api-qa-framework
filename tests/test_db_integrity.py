"""White-box checks: verify the database after API calls (ledger and balances must reconcile)."""
import sqlite3
from contextlib import closing

import pytest

pytestmark = pytest.mark.db


def _query(db_path, sql, params=()):
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        return conn.execute(sql, params).fetchall()


def test_each_transfer_writes_one_debit_and_one_credit_of_equal_value(api, funded_pair, db_path):
    source, destination = funded_pair
    transfer = api.transfer(source["id"], destination["id"], 1_234).json()

    rows = _query(db_path, "SELECT account_id, direction, amount FROM ledger_entries "
                           "WHERE transfer_id = ?", (transfer["id"],))
    assert sorted(rows) == sorted([(source["id"], "DEBIT", 1_234),
                                   (destination["id"], "CREDIT", 1_234)])


def test_rejected_transfers_leave_no_ledger_or_transfer_rows(api, funded_pair, db_path):
    source, destination = funded_pair
    before = _query(db_path, "SELECT COUNT(*) FROM ledger_entries")[0][0]
    api.transfer(source["id"], destination["id"], 99_999_999)
    api.transfer(source["id"], source["id"], 10)
    assert _query(db_path, "SELECT COUNT(*) FROM ledger_entries")[0][0] == before


def test_account_balance_equals_opening_balance_plus_net_ledger(api, funded_pair, db_path):
    source, destination = funded_pair
    for amount in (100, 250, 400):
        api.transfer(source["id"], destination["id"], amount)
    api.transfer(destination["id"], source["id"], 50)

    for account, opening in ((source, 10_000), (destination, 0)):
        net = _query(db_path, "SELECT COALESCE(SUM(CASE direction WHEN 'CREDIT' THEN amount "
                              "ELSE -amount END), 0) FROM ledger_entries WHERE account_id = ?",
                     (account["id"],))[0][0]
        balance = _query(db_path, "SELECT balance FROM accounts WHERE id = ?", (account["id"],))[0][0]
        assert balance == opening + net


def test_system_wide_ledger_nets_to_zero_and_no_balance_is_negative(api, funded_pair, db_path):
    source, destination = funded_pair
    api.transfer(source["id"], destination["id"], 700)
    net = _query(db_path, "SELECT COALESCE(SUM(CASE direction WHEN 'CREDIT' THEN amount "
                          "ELSE -amount END), 0) FROM ledger_entries")[0][0]
    negative = _query(db_path, "SELECT COUNT(*) FROM accounts WHERE balance < 0")[0][0]
    assert net == 0
    assert negative == 0


def test_idempotent_replay_does_not_create_extra_rows(api, funded_pair, db_path):
    source, destination = funded_pair
    first = api.transfer(source["id"], destination["id"], 300, key="db-replay-key-1").json()
    api.transfer(source["id"], destination["id"], 300, key="db-replay-key-1")
    rows = _query(db_path, "SELECT COUNT(*) FROM ledger_entries WHERE transfer_id = ?", (first["id"],))
    assert rows[0][0] == 2
