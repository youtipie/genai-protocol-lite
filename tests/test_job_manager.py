import asyncio
import unittest
from unittest.mock import AsyncMock

from AIConnector.core.job_manager import JobManager
from AIConnector.common.message import MessageTypes


# Dummy sender callback to record messages sent by JobManager.
class DummySender:
    def __init__(self):
        self.messages = []

    async def __call__(self, **kwargs):
        self.messages.append(kwargs)


# A dummy job callable that simulates processing.
async def dummy_job_callable(data):
    await asyncio.sleep(0.05)
    return f"processed {data}"


class TestJobManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sender = DummySender()
        self.job_manager = JobManager(send_message_callback=self.sender)

    async def test_create_job(self):
        # Test that create_job sends two system messages and registers the job.
        job_id = await self.job_manager.create_job("data1", dummy_job_callable, "peer1", "q1")
        # Two messages: one for initialization and one for starting.
        self.assertEqual(len(self.sender.messages), 2)
        init_msg = self.sender.messages[0]
        start_msg = self.sender.messages[1]
        self.assertEqual(init_msg["message_type"], MessageTypes.SYSTEM_MESSAGE.value)
        self.assertIn("Job initialized", init_msg["text"])
        self.assertEqual(start_msg["message_type"], MessageTypes.SYSTEM_MESSAGE.value)
        self.assertIn("Job started", start_msg["text"])

        # Check that the job exists in active_jobs and a future is registered.
        self.assertIn(job_id, self.job_manager.active_jobs)
        self.assertIn(job_id, self.job_manager.job_futures)
        # Wait for the job's task to complete.
        result = await self.job_manager.active_jobs[job_id].task
        self.assertEqual(result, "processed data1")

    async def test_await_job_result(self):
        # Create a job and then start monitoring so that the job's future gets updated.
        job_id = await self.job_manager.create_job("data2", dummy_job_callable, "peer2", "q2")
        # Start monitoring to update the future.
        self.job_manager.start(interval=0.01)
        result = await self.job_manager.await_job_result(job_id, timeout=1)
        self.assertEqual(result, "processed data2")
        await self.job_manager.stop()

    async def test_start_monitoring_and_heartbeat(self):
        # Create a slow job to test heartbeat messages.
        async def slow_job(data):
            await asyncio.sleep(0.2)
            return f"slow {data}"

        job_id = await self.job_manager.create_job("data3", slow_job, "peer3", "q3")
        self.job_manager.start(interval=0.05)
        # Let monitoring run for a short while.
        await asyncio.sleep(0.15)
        # Check that heartbeat messages were sent.
        heartbeat_msgs = [
            m for m in self.sender.messages
            if m.get("message_type") == MessageTypes.HEARTBEAT.value
        ]
        self.assertGreater(len(heartbeat_msgs), 0)
        # Wait for the job to complete and get its result.
        result = await self.job_manager.await_job_result(job_id, timeout=1)
        self.assertEqual(result, "slow data3")
        # After finishing, the job should be removed from active_jobs.
        self.assertNotIn(job_id, self.job_manager.active_jobs)
        await self.job_manager.stop()

    async def test_stop_monitoring(self):
        # Start monitoring and then stop it, verifying that the monitoring task is cancelled.
        self.job_manager.start(interval=0.05)
        self.assertIsNotNone(self.job_manager.monitoring_task)
        await self.job_manager.stop()
        self.assertTrue(self.job_manager.monitoring_task.cancelled())

    async def test_process_message(self):
        # Register a dummy job callable and process an incoming message.
        dummy_callable = AsyncMock(return_value="processed msg")
        self.job_manager.register_job(dummy_callable)
        # Clear any previous messages.
        self.sender.messages.clear()
        await self.job_manager.process_message("test message", "peer4", "q4")
        # Wait for the created job task(s) to complete.
        if self.job_manager.active_jobs:
            tasks = [
                job.task for job in self.job_manager.active_jobs.values()
                if job.task is not None
            ]
            if tasks:
                await asyncio.gather(*tasks)
        # Expect messages from create_job (initialization and started) plus an acknowledgment.
        self.assertGreaterEqual(len(self.sender.messages), 3)
        # Verify that the dummy job callable was called with the message.
        dummy_callable.assert_awaited_with("test message")

    async def test_register_and_job_list(self):
        # Test that registering a job callable adds it to the job list.
        async def dummy_callable(data):
            return data

        self.job_manager.register_job(dummy_callable)
        job_list = self.job_manager.job_list()
        self.assertIn(dummy_callable, job_list)

    async def test_job_active_list(self):
        # Create a job and verify that it appears in the active job list.
        job_id = await self.job_manager.create_job("data4", dummy_job_callable, "peer5", "q5")
        active_jobs = self.job_manager.job_active_list()
        self.assertIn(job_id, active_jobs)


if __name__ == "__main__":
    unittest.main()
