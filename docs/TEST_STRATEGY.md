# Test Strategy: Payments API

## Scope
Functional, negative, contract, concurrency, rate-limit, database-integrity and performance testing of
the Payments API (`/auth/token`, `/accounts`, `/transfers`).
Out of scope: UI, third-party integrations, security penetration testing.

## Risk-based priorities

| # | Risk | Impact | Likelihood | How it is covered |
|---|---|---|---|---|
| 1 | Money lost or created (balances and ledger diverge) | Critical | Medium | Balance assertions on every transfer test, ledger reconciliation tests in `test_db_integrity.py` |
| 2 | Double debit on client retry | Critical | High | Idempotency tests, including 10 parallel duplicate requests |
| 3 | Overdraft under concurrent load | Critical | Medium | 20 parallel transfers against a 1,000 balance; exactly 10 may succeed |
| 4 | Unauthorised access | High | Medium | Every protected endpoint tested without a token, with malformed and unknown tokens |
| 5 | Bad input corrupts data | High | High | Boundary and type-strictness tests (negative, zero, string, float, boolean amounts) |
| 6 | Abuse or runaway clients | Medium | Medium | Rate-limit tests: `429`, `Retry-After`, per-token isolation, reset |
| 7 | Clients break on inconsistent errors | Medium | Medium | Single error envelope validated against a JSON Schema |
| 8 | Slowdown under load | Medium | Medium | k6 load test with p95 and error-rate thresholds |

## Test levels and tooling

| Level | Tool | When it runs |
|---|---|---|
| Smoke | pytest `-m smoke` | Every commit, first gate |
| Regression (API) | pytest + httpx | Every push and pull request, plus nightly |
| Contract | pytest + jsonschema | With regression |
| Database integrity | pytest + sqlite3 (read-only) | With regression, local runs only |
| Performance | k6 | After tests pass in CI |

## Entry and exit criteria
- **Entry:** API starts and `/health` returns 200.
- **Exit:** smoke and regression suites 100% passing on both Python versions, k6 thresholds met,
  no open critical or high defects.

## Traceability (requirement to tests)

| Requirement | Test module |
|---|---|
| Clients authenticate with client credentials and receive a bearer token | `test_auth.py` |
| Accounts hold a single currency and a non-negative integer balance | `test_accounts.py` |
| A transfer moves funds atomically between two accounts of the same currency | `test_transfers.py`, `test_db_integrity.py` |
| Transfers require an `Idempotency-Key`; retries must not duplicate | `test_idempotency.py` |
| Balances never go negative, even under parallel load | `test_concurrency.py` |
| Transfers are limited per token | `test_rate_limit.py` |
| All errors use `{"error": {"code", "message"}}` | `test_contract.py` |

## Test data
Every test creates its own accounts through the API, so there is no shared fixture data and no
ordering dependency. Tests run safely in parallel (`pytest -n auto`).
