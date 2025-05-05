import asyncio
import json
import socket
import unittest
from unittest.mock import patch

from AIConnector.discovery.discovery_service import DiscoveryProtocol, DiscoveryService
from AIConnector.common.network import NetworkConfig


# A dummy transport to record sent datagrams.
class DummyTransport:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


class TestDiscoveryProtocol(unittest.TestCase):
    def setUp(self):
        self.callback_called = False
        self.received_msg = None
        self.received_addr = None

        def dummy_callback(msg, addr):
            self.callback_called = True
            self.received_msg = msg
            self.received_addr = addr

        self.callback = dummy_callback
        self.protocol = DiscoveryProtocol(self.callback)

    def test_datagram_received_valid(self):
        # Valid DISCOVERY message.
        msg = {
            "type": "DISCOVERY",
            "client_id": "client1",
            "allow_discovery": True,
            "display_name": "Tester",
            "port": 5000
        }
        data = json.dumps(msg).encode("utf-8")
        addr = ("192.168.0.1", 12345)
        self.protocol.datagram_received(data, addr)
        self.assertTrue(self.callback_called)
        self.assertEqual(self.received_msg, msg)
        self.assertEqual(self.received_addr, addr)

    def test_datagram_received_invalid_json(self):
        # Invalid JSON should not crash nor call the callback.
        invalid_data = b"not a json"
        addr = ("192.168.0.1", 12345)
        try:
            self.protocol.datagram_received(invalid_data, addr)
        except Exception as e:
            self.fail("datagram_received raised an exception on invalid JSON")
        self.assertFalse(self.callback_called)

    def test_datagram_received_non_discovery(self):
        # Valid JSON but not a DISCOVERY message.
        msg = {"type": "NOT_DISCOVERY"}
        data = json.dumps(msg).encode("utf-8")
        addr = ("192.168.0.1", 12345)
        self.protocol.datagram_received(data, addr)
        self.assertFalse(self.callback_called)


class TestDiscoveryService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Create a dummy NetworkConfig.
        self.network_config = NetworkConfig(
            advertisement_port=9999,
            advertisement_ip="224.1.1.1",
            advertisement_interval=0.1,  # fast interval for testing
            heartbeat_delay=5,
            webserver_port=5000,
            client_id="client1",
            peer_discovery_timeout=30,
            peer_ping_interval=5,
            webserver_autodiscovery_port_min=5000,
            webserver_autodiscovery_port_max=7000
        )
        self.callback_called = False
        self.callback_data = None
        self.callback_addr = None

        def dummy_callback(msg, addr):
            self.callback_called = True
            self.callback_data = msg
            self.callback_addr = addr

        self.dummy_callback = dummy_callback
        self.service = DiscoveryService(
            on_peer_discovered_callback=self.dummy_callback,
            client_name="Tester",
            port=5000,
            network_config=self.network_config
        )

    async def test_get_socket(self):
        # Verify that get_socket returns a non-blocking socket.
        sock = DiscoveryService.get_socket(
            self.network_config.advertisement_port,
            self.network_config.advertisement_ip
        )
        self.assertIsInstance(sock, socket.socket)
        self.assertFalse(sock.getblocking())
        sock.close()

    async def test_start_and_periodic_announce(self):
        # Patch the event loop's create_datagram_endpoint to return our dummy transport.
        dummy_transport = DummyTransport()

        async def fake_create_datagram_endpoint(protocol_factory, sock):
            return dummy_transport, None

        loop = asyncio.get_event_loop()
        with patch.object(loop, "create_datagram_endpoint", side_effect=fake_create_datagram_endpoint):
            await self.service.start(allow_discovery=True)
            # Allow several announcement intervals to pass.
            await asyncio.sleep(0.35)
            # Check that at least one announcement has been sent.
            self.assertGreater(len(dummy_transport.sent), 0)
            sent_data, addr = dummy_transport.sent[0]
            sent_msg = json.loads(sent_data.decode("utf-8"))
            self.assertEqual(sent_msg.get("type"), "DISCOVERY")
            self.assertEqual(sent_msg.get("client_id"), self.network_config.client_id)
            # Stop the service.
            await self.service.stop()
            self.assertFalse(self.service.running)
            self.assertTrue(dummy_transport.closed)

    async def test_stop_without_start(self):
        # Calling stop before start should not raise an exception.
        try:
            await self.service.stop()
        except Exception as e:
            self.fail(f"stop() raised an exception when not started: {e}")


if __name__ == "__main__":
    unittest.main()
