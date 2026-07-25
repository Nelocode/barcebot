import asyncio
import unittest

from telegram_call_rejection import TelegramCallRejectCoordinator


class TelegramCallRejectCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_updates_share_one_operation_and_wait_for_its_result(self):
        coordinator = TelegramCallRejectCoordinator(limit=8)
        operation_started = asyncio.Event()
        release_operation = asyncio.Event()
        operation_calls = 0

        async def reject_call():
            nonlocal operation_calls
            operation_calls += 1
            operation_started.set()
            await release_operation.wait()
            return "sent"

        first = asyncio.create_task(coordinator.execute(700, reject_call))
        await operation_started.wait()
        second = asyncio.create_task(coordinator.execute(700, reject_call))
        await asyncio.sleep(0)

        self.assertFalse(first.done())
        self.assertFalse(second.done())
        self.assertEqual(1, operation_calls)

        release_operation.set()
        self.assertEqual(["sent", "sent"], await asyncio.gather(first, second))
        self.assertEqual(1, operation_calls)

    async def test_sent_and_already_finished_results_remain_deduplicated(self):
        for call_id, terminal_status in ((701, "sent"), (702, "already_finished")):
            with self.subTest(status=terminal_status):
                coordinator = TelegramCallRejectCoordinator(limit=8)
                operation_calls = 0

                async def reject_call():
                    nonlocal operation_calls
                    operation_calls += 1
                    return terminal_status

                self.assertEqual(
                    terminal_status,
                    await coordinator.execute(call_id, reject_call),
                )
                self.assertEqual(
                    terminal_status,
                    await coordinator.execute(call_id, reject_call),
                )
                self.assertEqual(1, operation_calls)

    async def test_failed_result_is_returned_and_allows_retry(self):
        coordinator = TelegramCallRejectCoordinator(limit=8)
        operation_calls = 0

        async def reject_call():
            nonlocal operation_calls
            operation_calls += 1
            return "failed" if operation_calls == 1 else "sent"

        self.assertEqual("failed", await coordinator.execute(703, reject_call))
        self.assertEqual("sent", await coordinator.execute(703, reject_call))
        self.assertEqual(2, operation_calls)

    async def test_timed_out_result_is_returned_and_allows_retry(self):
        coordinator = TelegramCallRejectCoordinator(limit=8)
        operation_calls = 0

        async def reject_call():
            nonlocal operation_calls
            operation_calls += 1
            return "timed_out" if operation_calls == 1 else "sent"

        self.assertEqual("timed_out", await coordinator.execute(704, reject_call))
        self.assertEqual("sent", await coordinator.execute(704, reject_call))
        self.assertEqual(2, operation_calls)

    async def test_operation_errors_are_fail_open_and_do_not_consume_call(self):
        coordinator = TelegramCallRejectCoordinator(limit=8)
        downstream_reached = False

        async def broken_rejection():
            raise RuntimeError("transport unavailable")

        result = await coordinator.execute(705, broken_rejection)
        downstream_reached = True

        self.assertEqual("failed", result)
        self.assertTrue(downstream_reached)

        async def retry_rejection():
            return "sent"

        self.assertEqual("sent", await coordinator.execute(705, retry_rejection))

    async def test_timeout_errors_are_fail_open_and_do_not_consume_call(self):
        coordinator = TelegramCallRejectCoordinator(limit=8)

        async def timed_out_rejection():
            raise asyncio.TimeoutError

        self.assertEqual(
            "timed_out",
            await coordinator.execute(706, timed_out_rejection),
        )

        async def retry_rejection():
            return "sent"

        self.assertEqual("sent", await coordinator.execute(706, retry_rejection))

if __name__ == "__main__":
    unittest.main()
