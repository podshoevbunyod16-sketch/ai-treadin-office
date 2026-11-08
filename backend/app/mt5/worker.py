"""Entry point of the dedicated per-account MT5 worker process (connection type ``local``).

The official MetaTrader5 package is a process-wide singleton bound to one terminal, therefore every
broker account gets its own OS process. This isolates accounts from each other and from the web server.
"""
from __future__ import annotations

import traceback


def worker_main(conn) -> None:  # pragma: no cover - executed in a child process (covered by integration tests)
    from .client import MT5Client, MT5Error, MT5Unavailable, dispatch

    try:
        client = MT5Client()
    except MT5Unavailable as exc:
        conn.send(("init_error", str(exc)))
        conn.close()
        return
    conn.send(("ready", None))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if msg is None:
            break
        req_id, method, params = msg
        try:
            conn.send((req_id, True, dispatch(client, method, params), None))
        except MT5Error as exc:
            conn.send((req_id, False, str(exc), exc.code))
        except Exception as exc:  # noqa: BLE001
            conn.send((req_id, False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}", None))
    try:
        client.disconnect()
    except Exception:  # noqa: BLE001
        pass
