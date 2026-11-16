# Payments API QA Framework

[![CI](https://github.com/reubenamissah/payments-api-qa-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/reubenamissah/payments-api-qa-framework/actions/workflows/ci.yml)

An end-to-end **API test automation project** for a fintech-style payments service: a pytest framework,
a CI/CD pipeline, load testing, and Docker support. It shows how I approach quality on money-moving
systems: correctness of balances, safe retries, concurrency, throttling and consistent error contracts.

The repository includes a small **payments API** (FastAPI + SQLite) as the system under test, so
everything runs on any machine with no external services or accounts.

## What is tested

| Area | What the tests prove | Tests |
|---|---|---|
| **Auth** | Token issuing, bad/missing/malformed credentials, every protected endpoint rejects anonymous calls | 17 |
| **Accounts** | Create/fetch, boundary values (1 to 100 char names, 0 to 1bn balance), type strictness (`"500"`, `10.5`, `true` rejected), unknown fields | 19 |
| **Transfers** | Balances move correctly, amount and narration boundaries, insufficient funds, same account, unknown accounts, currency mismatch | 26 |
| **Idempotency** | A replayed `Idempotency-Key` never double-debits; a reused key with a different body gives `409`; 10 parallel duplicates debit once | 5 |
| **Concurrency** | 20 parallel transfers can never overdraw an account; opposite-direction transfers conserve total money | 2 |
| **Rate limiting** | `429` + `Retry-After` after the limit, per-token isolation, quota resets after the window | 4 |
| **Contract** | Responses validated against JSON Schema; every error uses one envelope; field-level validation errors | 3 |
| **DB integrity** | Every transfer = one debit + one credit; balances reconcile with the ledger; rejected requests leave no rows | 5 |
| **Health / docs** | Health check, request-id tracing header, OpenAPI document, standard 404 | 5 |
| **Total** | | **86** |

Tests are tagged (`smoke`, `regression`, `negative`, `contract`, `idempotency`, `concurrency`,
`ratelimit`, `db`, `slow`) so a pipeline can run a fast gate first and the full suite after.

## Do the tests catch real bugs?

A green suite proves little unless it fails when the product is broken. I injected four defects into a
copy of the API and checked that the suite turned red each time:

| Injected defect | Result |
|---|---|
| Insufficient-funds check removed | 3 tests failed |
| Idempotency replay ignored (double debit) | 5 tests failed |
| Credit side of a transfer dropped (money disappears) | 8 tests failed |
| Rate limiter disabled | 3 tests failed |

## Run it yourself

```bash
git clone https://github.com/reubenamissah/payments-api-qa-framework.git
cd payments-api-qa-framework
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

pytest -m smoke           # 8 tests, under 1 second
pytest -n auto            # all 86 tests in parallel, about 10 seconds
make report               # also writes reports/report.html and reports/junit.xml
```

The test session starts its own API instance on a free port. To test an API that is already running,
set `BASE_URL` (database-level tests are skipped in that mode):

```bash
make api                                   # terminal 1: API on :8000, interactive docs at /docs
BASE_URL=http://localhost:8000 pytest      # terminal 2
```

**Load test** (needs [k6](https://k6.io)):

```bash
RATE_LIMIT_PER_MINUTE=1000000 uvicorn app.main:app &
k6 run -e BASE_URL=http://localhost:8000 perf/transfers.js
```

Measured on my machine with 20 virtual users for 35 seconds: 4,904 transfer iterations, 0 failed
requests, 0 failed checks, p95 latency about 17 ms. Thresholds in the script (p95 < 500 ms, error
rate < 1%) fail the build if they are missed.

**Docker:** `make docker-test` builds the API image and runs the suite against the container.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` runs on every push and pull request, and nightly at 05:00 UTC:

1. **lint**: `ruff`
2. **api-tests**: Python 3.11 and 3.12 matrix; smoke gate first, then the full parallel suite; HTML and
   JUnit reports uploaded as artifacts; pass/fail table written to the job summary
3. **performance**: k6 load test with pass/fail thresholds
4. **docker**: image build and the suite run against the container

## Design decisions

- **API client layer** (`tests/api_client.py`): tests read like scenarios (`api.transfer(a, b, 500)`),
  and a change to the API means one edit, not fifty.
- **Isolated tests**: each test creates its own accounts and token, so tests can run in parallel in
  any order with no shared state.
- **Money as integers**: amounts are minor units, and the tests assert that floats and strings are
  rejected.
- **Black-box and white-box**: HTTP assertions plus direct ledger checks in the database.
- **Business-readable failures**: each test name states the rule it protects. See
  [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) for the risk analysis and traceability.

## Project layout

```
app/          system under test (FastAPI + SQLite)
tests/        pytest suite, API client, JSON schemas
perf/         k6 load test
scripts/      CI helper (JUnit to Markdown summary)
docs/         test strategy
.github/      CI pipeline
```

## Ideas for next steps

- Add mutation testing with `mutmut` instead of hand-injected defects
- Add Pact consumer-driven contract tests
- Publish Allure reports to GitHub Pages
- Add authorisation scenarios (account ownership) with a second API client
