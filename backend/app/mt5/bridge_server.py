"""MT5 bridge agent.

Run it on the Windows machine (or Wine prefix) where the MetaTrader 5 terminal is installed::

    pip install -r requirements.txt
    set ATO_BRIDGE_TOKEN=<long random token>
    python -m app.mt5.bridge_server --host 0.0.0.0 --port 8765 [--ssl-certfile cert.pem --ssl-keyfile key.pem]

One bridge process serves exactly one terminal (one trading account). The backend then uses an account
with connection type ``bridge`` pointing at ``http(s)://<host>:8765`` and the same token.
"""
from __future__ import annotations

import argparse
import hmac
import os
import platform
import threading
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .client import MT5Client, MT5Error, MT5Unavailable, dispatch
from .gateway import BRIDGE_PROTOCOL_VERSION


class RpcRequest(BaseModel):
    method: str
    params: dict[str, Any] = {}


def create_bridge_app(token: str, client_factory: Callable[[], MT5Client] = MT5Client) -> FastAPI:
    if not token or len(token) < 24:
        raise SystemExit("ATO_BRIDGE_TOKEN должен быть задан и содержать минимум 24 символа")
    app = FastAPI(title="AI Trading Office – MT5 bridge", docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()
    state: dict[str, Any] = {"client": None, "error": None}

    def get_client() -> MT5Client:
        if state["client"] is None:
            try:
                state["client"] = client_factory()
                state["error"] = None
            except MT5Unavailable as exc:
                state["error"] = str(exc)
                raise
        return state["client"]

    def check(auth: str | None) -> None:
        expected = f"Bearer {token}"
        if not auth or not hmac.compare_digest(auth.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    def health(authorization: str | None = Header(default=None)):
        check(authorization)
        ok = True
        try:
            client = get_client()
        except MT5Unavailable:
            ok, client = False, None
        return {"protocol": BRIDGE_PROTOCOL_VERSION, "mt5_package": ok, "error": state["error"],
                "connected": bool(client and client.connected), "platform": platform.platform()}

    def _run(req: RpcRequest) -> dict:
        with lock:
            try:
                client = get_client()
                return {"ok": True, "result": dispatch(client, req.method, req.params)}
            except MT5Error as exc:
                return {"ok": False, "error": str(exc), "code": exc.code}
            except TypeError as exc:
                return {"ok": False, "error": f"Неверные параметры: {exc}", "code": None}

    @app.post("/rpc")
    async def rpc(req: RpcRequest, authorization: str | None = Header(default=None)):
        check(authorization)
        return await run_in_threadpool(_run, req)

    return app


def main() -> None:  # pragma: no cover - CLI
    import uvicorn

    p = argparse.ArgumentParser(description="AI Trading Office MT5 bridge")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", default=os.environ.get("ATO_BRIDGE_TOKEN", ""))
    p.add_argument("--ssl-certfile")
    p.add_argument("--ssl-keyfile")
    a = p.parse_args()
    uvicorn.run(create_bridge_app(a.token), host=a.host, port=a.port,
                ssl_certfile=a.ssl_certfile, ssl_keyfile=a.ssl_keyfile, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
