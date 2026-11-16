"""Thin API client so tests read like business scenarios instead of raw HTTP calls."""
import uuid

import httpx

DEFAULT_CLIENT_ID = "qa-client"
DEFAULT_CLIENT_SECRET = "qa-secret"


class PaymentsAPI:
    def __init__(self, base_url: str):
        self.http = httpx.Client(base_url=base_url, timeout=10)
        self.token = None

    # -- auth -----------------------------------------------------------------
    def request_token(self, client_id=DEFAULT_CLIENT_ID, client_secret=DEFAULT_CLIENT_SECRET):
        return self.http.post("/auth/token",
                              json={"client_id": client_id, "client_secret": client_secret})

    def authenticate(self):
        response = self.request_token()
        assert response.status_code == 200, response.text
        self.token = response.json()["access_token"]
        return self

    def headers(self, extra=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return {**headers, **(extra or {})}

    # -- accounts -------------------------------------------------------------
    def create_account(self, owner_name="QA User", currency="NGN", initial_balance=0, **override):
        payload = {"owner_name": owner_name, "currency": currency,
                   "initial_balance": initial_balance, **override}
        return self.http.post("/accounts", json=payload, headers=self.headers())

    def new_account(self, **kwargs) -> dict:
        response = self.create_account(**kwargs)
        assert response.status_code == 201, response.text
        return response.json()

    def get_account(self, account_id):
        return self.http.get(f"/accounts/{account_id}", headers=self.headers())

    def balance(self, account_id) -> int:
        return self.get_account(account_id).json()["balance"]

    # -- transfers ------------------------------------------------------------
    def transfer(self, source, destination, amount, currency="NGN", key=None, narration=None,
                 headers=None, **override):
        payload = {"source_account_id": source, "destination_account_id": destination,
                   "amount": amount, "currency": currency, **override}
        if narration is not None:
            payload["narration"] = narration
        key = key or uuid.uuid4().hex
        return self.http.post("/transfers", json=payload,
                              headers=self.headers({"Idempotency-Key": key, **(headers or {})}))

    def get_transfer(self, transfer_id):
        return self.http.get(f"/transfers/{transfer_id}", headers=self.headers())

    def close(self):
        self.http.close()
