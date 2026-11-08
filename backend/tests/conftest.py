from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

TESTKIT = str(Path(__file__).parent / "mt5_testkit")
_tmp = tempfile.mkdtemp(prefix="ato-test-")
os.environ["ATO_DATA_DIR"] = _tmp
os.environ["ATO_FRONTEND_DIST"] = str(Path(_tmp) / "no-frontend")
os.environ["ATO_QUOTE_INTERVAL_MS"] = "200"
os.environ["ATO_ACCOUNT_INTERVAL_MS"] = "300"
os.environ["ATO_RECONNECT_INTERVAL_S"] = "1"

from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.mt5.bridge_server import create_bridge_app  # noqa: E402
from app.mt5.client import MT5Client  # noqa: E402
from app.mt5.gateway import BridgeGateway  # noqa: E402
from app.security import decrypt_secret  # noqa: E402

sys.path.insert(0, TESTKIT)
from fake_terminal import FakeTerminal  # noqa: E402

BRIDGE_TOKEN = "test-bridge-token-0123456789abcdef"


@pytest.fixture
def terminal() -> FakeTerminal:
    return FakeTerminal()


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    get_settings.cache_clear()
    app_db.init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield


@pytest.fixture
def bridge_app(terminal):
    return create_bridge_app(BRIDGE_TOKEN, client_factory=lambda: MT5Client(terminal))


@pytest.fixture
def use_bridge(bridge_app):
    """Route every 'bridge' account of the AccountManager to the in-process bridge app."""
    from app.state import accounts

    def factory(acc):
        return BridgeGateway("http://bridge.test", decrypt_secret(acc.bridge_token_enc) or "",
                             transport=httpx.ASGITransport(app=bridge_app))

    old = accounts.gateway_factory
    accounts.gateway_factory = factory
    yield
    accounts.gateway_factory = old


@pytest.fixture
async def app_client():
    from app.main import create_app
    from app.security import login_throttle

    login_throttle._fails.clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
    from app.state import accounts

    accounts.runtimes.clear()


async def make_admin(c: httpx.AsyncClient) -> dict:
    r = await c.post("/api/auth/setup", json={"username": "admin", "password": "Sup3r-secret-pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def wait_for(pred, timeout=10.0, interval=0.05):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        v = pred()
        if asyncio.iscoroutine(v):
            v = await v
        if v:
            return v
        await asyncio.sleep(interval)
    raise AssertionError("condition not met in time")
