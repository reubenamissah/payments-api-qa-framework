"""Mini payments API used as the system under test (SUT) for the QA framework.

Money is stored as integer minor units (e.g. kobo) to avoid floating point errors.
All state lives in a SQLite file so tests can also verify the database directly.
"""
import hashlib
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

DB_PATH = os.getenv("DB_PATH", "payments.db")
CLIENT_ID = os.getenv("CLIENT_ID", "qa-client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "qa-secret")
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
RATE_WINDOW = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
TOKEN_TTL_SECONDS = 3600

Currency = Literal["NGN", "GHS", "USD"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    owner_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    balance INTEGER NOT NULL CHECK (balance >= 0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    narration TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount INTEGER NOT NULL
);
"""

_write_lock = threading.Lock()
_tokens: dict[str, float] = {}
_hits: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def error_response(status, code, message, headers=None, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@asynccontextmanager
async def lifespan(_app):
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
    yield


app = FastAPI(title="Payments API (QA sandbox)", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    return response


@app.exception_handler(APIError)
async def api_error_handler(_req, exc: APIError):
    return error_response(exc.status, exc.code, exc.message, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_req, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "issue": e["msg"]}
        for e in exc.errors()
    ]
    return error_response(422, "VALIDATION_ERROR", "Request validation failed", details=details)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_req, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail))


# ----------------------------------------------------------------------------- models
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenRequest(StrictModel):
    client_id: str
    client_secret: str


class AccountIn(StrictModel):
    owner_name: str = Field(min_length=1, max_length=100)
    currency: Currency
    initial_balance: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)


class TransferIn(StrictModel):
    source_account_id: str
    destination_account_id: str
    amount: int = Field(gt=0, le=10_000_000, strict=True)
    currency: Currency
    narration: str | None = Field(default=None, max_length=140)


# ----------------------------------------------------------------------------- security
bearer_scheme = HTTPBearer(auto_error=False)  # registers the "Authorize" button in /docs


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise APIError(401, "UNAUTHORIZED", "Missing or malformed Authorization header",
                       {"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    expires = _tokens.get(token)
    if expires is None or expires < time.time():
        raise APIError(401, "UNAUTHORIZED", "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    return token


def rate_limit_transfers(request: Request, token: str = Depends(require_token)) -> dict:
    """Sliding window limiter, one bucket per access token."""
    now = time.monotonic()
    with _rate_lock:
        hits = _hits[token]
        while hits and now - hits[0] >= RATE_WINDOW:
            hits.popleft()
        if len(hits) >= RATE_LIMIT:
            retry_after = max(1, math.ceil(RATE_WINDOW - (now - hits[0])))
            raise APIError(429, "RATE_LIMITED", "Too many transfer requests", {
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(RATE_LIMIT),
                "X-RateLimit-Remaining": "0",
            })
        hits.append(now)
        remaining = RATE_LIMIT - len(hits)
    return {"X-RateLimit-Limit": str(RATE_LIMIT), "X-RateLimit-Remaining": str(remaining)}


# ----------------------------------------------------------------------------- helpers
def account_view(row) -> dict:
    return {"id": row["id"], "owner_name": row["owner_name"], "currency": row["currency"],
            "balance": row["balance"], "created_at": row["created_at"]}


def transfer_view(row) -> dict:
    return {"id": row["id"], "source_account_id": row["source_account_id"],
            "destination_account_id": row["destination_account_id"], "amount": row["amount"],
            "currency": row["currency"], "narration": row["narration"], "status": row["status"],
            "created_at": row["created_at"]}


# ----------------------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/token")
def issue_token(body: TokenRequest):
    valid = secrets.compare_digest(body.client_id, CLIENT_ID) and \
        secrets.compare_digest(body.client_secret, CLIENT_SECRET)
    if not valid:
        raise APIError(401, "INVALID_CREDENTIALS", "Invalid client credentials")
    token = secrets.token_hex(24)
    _tokens[token] = time.time() + TOKEN_TTL_SECONDS
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}


@app.post("/accounts", status_code=201)
def create_account(body: AccountIn, _token: str = Depends(require_token)):
    account_id = f"acc_{uuid.uuid4().hex[:12]}"
    with _write_lock, closing(connect()) as conn:
        conn.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                     (account_id, body.owner_name, body.currency, body.initial_balance, now_iso()))
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return account_view(row)


@app.get("/accounts/{account_id}")
def get_account(account_id: str, _token: str = Depends(require_token)):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise APIError(404, "ACCOUNT_NOT_FOUND", f"Account {account_id} not found")
    return account_view(row)


@app.post("/transfers")
def create_transfer(
    body: TransferIn,
    rate_headers: dict = Depends(rate_limit_transfers),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if idempotency_key is None:
        raise APIError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")
    if not 8 <= len(idempotency_key) <= 64:
        raise APIError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 8-64 characters")
    if body.source_account_id == body.destination_account_id:
        raise APIError(422, "SAME_ACCOUNT", "Source and destination accounts must differ")

    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()

    with _write_lock, closing(connect()) as conn:
        existing = conn.execute(
            "SELECT * FROM transfers WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise APIError(409, "IDEMPOTENCY_KEY_REUSED",
                               "Idempotency-Key was already used with a different request")
            return JSONResponse(transfer_view(existing), status_code=200,
                                headers={**rate_headers, "Idempotent-Replay": "true"})

        src = conn.execute("SELECT * FROM accounts WHERE id = ?", (body.source_account_id,)).fetchone()
        dst = conn.execute("SELECT * FROM accounts WHERE id = ?",
                           (body.destination_account_id,)).fetchone()
        if src is None or dst is None:
            missing = body.source_account_id if src is None else body.destination_account_id
            raise APIError(404, "ACCOUNT_NOT_FOUND", f"Account {missing} not found")
        if not (src["currency"] == dst["currency"] == body.currency):
            raise APIError(422, "CURRENCY_MISMATCH", "Transfer and both accounts must share a currency")
        if src["balance"] < body.amount:
            raise APIError(422, "INSUFFICIENT_FUNDS", "Source account has insufficient funds")

        transfer_id = f"trf_{uuid.uuid4().hex[:12]}"
        conn.execute("BEGIN")
        try:
            conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (body.amount, src["id"]))
            conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (body.amount, dst["id"]))
            conn.execute("INSERT INTO transfers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                transfer_id, idempotency_key, fingerprint, src["id"], dst["id"], body.amount,
                body.currency, body.narration, "COMPLETED", now_iso()))
            conn.execute("INSERT INTO ledger_entries (transfer_id, account_id, direction, amount) "
                         "VALUES (?, ?, 'DEBIT', ?)", (transfer_id, src["id"], body.amount))
            conn.execute("INSERT INTO ledger_entries (transfer_id, account_id, direction, amount) "
                         "VALUES (?, ?, 'CREDIT', ?)", (transfer_id, dst["id"], body.amount))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        row = conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone()
    return JSONResponse(transfer_view(row), status_code=201, headers=rate_headers)


@app.get("/transfers/{transfer_id}")
def get_transfer(transfer_id: str, _token: str = Depends(require_token)):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone()
    if row is None:
        raise APIError(404, "TRANSFER_NOT_FOUND", f"Transfer {transfer_id} not found")
    return transfer_view(row)
