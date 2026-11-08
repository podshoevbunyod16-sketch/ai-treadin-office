from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import accounts as accounts_api
from .api import auth, bots as bots_api, system, ws
from .config import get_settings
from .db import get_engine
from .mt5.client import MT5Error, MT5Unavailable
from .services.accounts import AccountNotConnected, TradingForbidden
from .services.hub import hub
from .state import accounts, bots

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    await accounts.start()
    await bots.restore()
    yield
    await bots.stop_all(persist=False)
    await accounts.shutdown()
    await hub.close_all()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                           allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(AccountNotConnected)
    async def _nc(_, exc: AccountNotConnected):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(TradingForbidden)
    async def _tf(_, exc: TradingForbidden):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(MT5Unavailable)
    async def _un(_, exc: MT5Unavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc), "mt5_unavailable": True})

    @app.exception_handler(MT5Error)
    async def _mt5(_, exc: MT5Error):
        return JSONResponse(status_code=502, content={"detail": str(exc), "code": exc.code})

    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(accounts_api.router)
    app.include_router(bots_api.router)
    app.include_router(ws.router)

    dist = s.frontend_dist
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/") or path == "ws":
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
