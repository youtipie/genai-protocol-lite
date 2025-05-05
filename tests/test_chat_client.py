import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from AIConnector.core.chat_client import ChatClient
from AIConnector.common.network import NetworkConfig


# Dummy connector simulating basic behavior.
class DummyConnector:
    def __init__(self):
        self.sent_messages = []
        self.peers_list = [{"peer_id": "peer1", "display_name": "Peer1"}]
        self.started = False
        self.stopped = False

    async def start(self, host, port, allow_discovery):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send_message(self, peer_id, msg):
        self.sent_messages.append((peer_id, msg))

    def get_peers_list(self):
        return self.peers_list


# Dummy JobManager to record process_message calls and other behaviors.
class DummyJobManager:
    def __init__(self):
        self.processed_messages = []
        self.job_list_value = []
        self.registered_job = None
        self.started = False
        self.stopped = False

    async def process_message(self, msg, from_id, queue_id):
        self.processed_messages.append((msg, from_id, queue_id))

    def job_list(self):
        return self.job_list_value

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    # Accept a keyword-only argument to match ChatClient.register_job call.
    def register_job(self, *, job_call_back):
        self.registered_job = job_call_back


class TestChatClient(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Create a dummy NetworkConfig.
        self.network_config = NetworkConfig(
            advertisement_port=9999,
            advertisement_ip="224.1.1.1",
            advertisement_interval=15,
            heartbeat_delay=5,
            webserver_port=5000,
            client_id="client1",
            webserver_autodiscovery_port_min=5000,
            webserver_autodiscovery_port_max=7000,
            peer_discovery_timeout=30,
            peer_ping_interval=5
        )
        # Create ChatClient instance.
        self.client = ChatClient(
            network_config=self.network_config,
            client_id="client1",
            client_name="Tester"
        )
        # Replace the connector and job_manager with dummy instances.
        self.dummy_connector = DummyConnector()
        self.client.connector = self.dummy_connector
        self.dummy_job_manager = DummyJobManager()
        self.client.job_manager = self.dummy_job_manager

    async def test_start_stop(self):
        # Patch P2PConnector to return our dummy connector.
        with patch("core.chat_client.P2PConnector", return_value=self.dummy_connector):
            # Override start and stop methods of our dummy connector.
            async def dummy_start(host, port, allow_discovery):
                self.dummy_connector.started = True

            async def dummy_stop():
                self.dummy_connector.stopped = True

            self.dummy_connector.start = dummy_start
            self.dummy_connector.stop = dummy_stop

            # Patch job_manager.start and stop.
            self.dummy_job_manager.start = lambda: setattr(self.dummy_job_manager, 'started', True)
            self.dummy_job_manager.stop = AsyncMock()

            await self.client.start(host="127.0.0.1")
            self.assertTrue(self.dummy_connector.started)
            self.assertTrue(self.dummy_job_manager.started)

            await self.client.stop()
            self.assertTrue(self.dummy_connector.stopped)
            self.dummy_job_manager.stop.assert_awaited()

    async def test_message_dispatch_text(self):
        # When a TEXT message is received, job_manager.process_message should be called.
        text_message = {
            "type": "text",
            "from_id": "peer1",
            "text": "Hello",
            "queue_id": "q1"
        }
        await self.client._on_message_received(text_message)
        self.assertIn(("Hello", "peer1", "q1"), self.dummy_job_manager.processed_messages)

    async def test_message_dispatch_hello(self):
        # Test that a HELLO message is dispatched to msg_type_hello.
        self.client.msg_type_hello = AsyncMock()
        hello_message = {"type": "hello", "from_id": "peer1"}
        await self.client._on_message_received(hello_message)
        self.client.msg_type_hello.assert_awaited_with(msg=hello_message)

    async def test_message_dispatch_unknown_defaults_to_text(self):
        # For an unknown message type, it should default to the TEXT handler.
        self.client.msg_type_text = AsyncMock()
        unknown_message = {
            "type": "unknown",
            "from_id": "peer1",
            "text": "Fallback",
            "queue_id": "q1"
        }
        await self.client._on_message_received(unknown_message)
        self.client.msg_type_text.assert_awaited_with(msg=unknown_message)

    async def test_msg_final_message(self):
        # Test that msg_final_message sets the result of the corresponding job future.
        future = asyncio.get_event_loop().create_future()
        self.client.pending_jobs_futures["q1"] = future
        final_message = {"type": "final_message", "queue_id": "q1", "text": "Done"}
        await self.client.msg_final_message(final_message)
        self.assertTrue(future.done())
        self.assertEqual(future.result(), "Done")

    async def test_wait_for_result_no_future(self):
        # Verify that wait_for_result raises a ValueError if no future is found.
        with self.assertRaises(ValueError):
            await self.client.wait_for_result("nonexistent", timeout=1)

    async def test_get_peers_list_and_filter(self):
        # Test that get_peers_list returns the peers from the connector,
        # and that get_peers_by_client_name correctly filters the list.
        peers_list = await self.client.get_peers_list()
        self.assertEqual(peers_list, [{"peer_id": "peer1", "display_name": "Peer1"}])
        # Modify peers list to test filtering.
        self.dummy_connector.peers_list = [
            {"peer_id": "peer1", "display_name": "Peer1"},
            {"peer_id": "peer2", "display_name": "Tester"}
        ]
        filtered = await self.client.get_peers_by_client_name("Tester")
        self.assertEqual(filtered, [{"peer_id": "peer2", "display_name": "Tester"}])

    async def test_wait_all_peers(self):
        # Test wait_all_peers by simulating that peers become available after a few checks.
        call_count = 0

        async def fake_get_peers_list():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return []
            return [{"peer_id": "peer1", "display_name": "Peer1"}]

        self.client.get_peers_list = fake_get_peers_list
        peers = await self.client.wait_all_peers(interval=0.1, timeout=1)
        self.assertEqual(peers, [{"peer_id": "peer1", "display_name": "Peer1"}])

    async def test_wait_for_peers(self):
        # Test wait_for_peers by simulating that a peer with a target name appears after a delay.
        call_count = 0

        async def fake_get_peers_by_client_name(target_client_name):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return []
            return [{"peer_id": "peer2", "display_name": target_client_name}]

        self.client.get_peers_by_client_name = fake_get_peers_by_client_name
        peer = await self.client.wait_for_peers("PeerTest", interval=0.1, timeout=1)
        self.assertEqual(peer, {"peer_id": "peer2", "display_name": "PeerTest"})

    async def test_send_typed_message(self):
        # Test that send_typed_message uses MessageFactory and calls _send_message.
        self.client._send_message = AsyncMock()
        await self.client.send_typed_message(peer_id="peer1", text="Hello", message_type="text", job_id="job1")
        self.client._send_message.assert_awaited()

    async def test_send_message_and_wait_for_result(self):
        # Test send_message by simulating a pending future that later gets resolved.
        self.client._send_message = AsyncMock()
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.client.pending_jobs_futures["queue123"] = future

        async def simulate_final_message():
            await asyncio.sleep(0.1)
            future.set_result("Response")

        asyncio.create_task(simulate_final_message())

        result = await self.client.wait_for_result("queue123", timeout=1)
        self.assertEqual(result, "Response")

    async def test_register_job(self):
        # Test that register_job correctly passes the job callable to the job_manager.
        dummy_job = AsyncMock()
        await self.client.register_job(dummy_job)
        self.assertEqual(self.dummy_job_manager.registered_job, dummy_job)


if __name__ == "__main__":
    unittest.main()
