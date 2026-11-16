import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

from tests.api_client import PaymentsAPI

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """Start the API locally on a free port, or use BASE_URL when testing a deployed one."""
    external = os.getenv("BASE_URL")
    if external:
        yield {"base_url": external.rstrip("/"), "db_path": None}
        return

    db_path = tmp_path_factory.mktemp("db") / "payments.db"
    port = _free_port()
    env = {**os.environ, "DB_PATH": str(db_path), "RATE_LIMIT_PER_MINUTE": "30",
           "RATE_LIMIT_WINDOW_SECONDS": "5"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
         "--log-level", "warning"], cwd=ROOT, env=env)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.exit("API did not start in time", returncode=2)
    yield {"base_url": base_url, "db_path": db_path}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(server):
    return server["base_url"]


@pytest.fixture
def anon(base_url):
    """Unauthenticated client."""
    client = PaymentsAPI(base_url)
    yield client
    client.close()


@pytest.fixture
def api(base_url):
    """Authenticated client with its own token, so each test gets its own rate-limit bucket."""
    client = PaymentsAPI(base_url).authenticate()
    yield client
    client.close()


@pytest.fixture
def funded_pair(api):
    """Two NGN accounts: a source with 10,000 and an empty destination."""
    return api.new_account(initial_balance=10_000), api.new_account(initial_balance=0)


@pytest.fixture
def db_path(server):
    if server["db_path"] is None:
        pytest.skip("Direct DB checks need a locally started API (BASE_URL is set)")
    return server["db_path"]


def load_schema(name: str) -> dict:
    import json
    return json.loads((ROOT / "tests" / "schemas" / f"{name}.json").read_text())
