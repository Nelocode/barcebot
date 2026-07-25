"""Ordered per-chat delivery for Telegram interactions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from interaction_state import InteractionDecision, PersistentInteractionState


class TelegramInteractionDispatcher:
    def __init__(
        self,
        state: PersistentInteractionState,
        send_response: Callable[[int, str, str], Awaitable[None]],
    ) -> None:
        self.state = state
        self.send_response = send_response
        self._locks: dict[int, asyncio.Lock] = {}

    async def dispatch(
        self,
        *,
        chat_id: int,
        event_id: str,
        kind: str,
        detected_language: str | None = None,
    ) -> InteractionDecision:
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            decision = self.state.register(
                contact_id=chat_id,
                event_id=event_id,
                kind=kind,
                detected_language=detected_language,
            )
            if not decision.duplicate and decision.response_key:
                await self.send_response(
                    chat_id,
                    decision.response_key,
                    decision.language,
                )
            return decision
