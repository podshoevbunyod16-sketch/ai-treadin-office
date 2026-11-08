"""Process-wide runtime singletons."""
from __future__ import annotations

from .bots.runner import BotManager
from .services.accounts import manager as accounts

bots = BotManager(accounts)
