"""TEST-ONLY module named like the official package so that the spawned MT5 worker process (connection
type ``local``) can be exercised in CI. Only placed on sys.path by tests/conftest.py."""
from fake_terminal import FakeTerminal

_terminal = FakeTerminal()


def __getattr__(name):
    return getattr(_terminal, name)
