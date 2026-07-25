"""Concurrency-safe coordination for Telegram call rejection attempts."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable


TERMINAL_STATUSES = {"sent", "already_finished"}
RETRYABLE_STATUSES = {"failed", "timed_out"}
VALID_STATUSES = TERMINAL_STATUSES | RETRYABLE_STATUSES


class TelegramCallRejectCoordinator:
    """Share one in-flight rejection and cache only terminal outcomes.

    Telegram may publish both ``PhoneCallRequested`` and ``PhoneCallWaiting``
    for the same call.  Both handlers must wait for the same discard RPC so a
    duplicate update cannot send the auto-response before rejection finishes.
    Failed attempts are deliberately not cached, allowing a later update to
    retry.
    """

    def __init__(self, *, limit: int = 256) -> None:
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self._limit = limit
        self._inflight: dict[int, asyncio.Task[str]] = {}
        self._waiters: dict[int, int] = {}
        self._completed: dict[int, str] = {}
        self._completed_order: deque[int] = deque()

    async def execute(
        self,
        call_id: int,
        operation: Callable[[], Awaitable[str]],
    ) -> str:
        """Run or join a rejection attempt and return a bounded status."""

        completed_status = self._completed.get(call_id)
        if completed_status is not None:
            return completed_status

        task = self._inflight.get(call_id)
        if task is None:
            task = asyncio.create_task(self._run(operation))
            self._inflight[call_id] = task
        self._waiters[call_id] = self._waiters.get(call_id, 0) + 1

        cancelled = False
        try:
            status = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            remaining_waiters = max(0, self._waiters.get(call_id, 1) - 1)
            if remaining_waiters:
                self._waiters[call_id] = remaining_waiters
            else:
                self._waiters.pop(call_id, None)
            if cancelled and not task.done() and not remaining_waiters:
                if self._inflight.get(call_id) is task:
                    self._inflight.pop(call_id, None)
                task.cancel()
            if task.done() and self._inflight.get(call_id) is task:
                self._inflight.pop(call_id, None)

        if status in TERMINAL_STATUSES:
            self._remember(call_id, status)
        return status

    @staticmethod
    async def _run(operation: Callable[[], Awaitable[str]]) -> str:
        try:
            status = await operation()
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            return "timed_out"
        except Exception:
            return "failed"
        return status if status in VALID_STATUSES else "failed"

    def _remember(self, call_id: int, status: str) -> None:
        if call_id in self._completed:
            return
        if len(self._completed_order) >= self._limit:
            expired = self._completed_order.popleft()
            self._completed.pop(expired, None)
        self._completed_order.append(call_id)
        self._completed[call_id] = status
