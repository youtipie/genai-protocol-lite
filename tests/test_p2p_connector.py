import asyncio
import time
import unittest
from unittest.mock import AsyncMock

from AIConnector.connector.peer_connection_manager import PeerConnectionManager
from AIConnector.common.network import NetworkConfig


# Dummy WebSocket connector simulating basic behavior.
class DummyWsConnector:
    def __init__(self):
        self.start_server_called = None
        self.stop_server_called = False
        self.connect_to_peer_called = []
        self.send_message_called = []

    async def start_server(self, host, port):
        self.start_server_called = (host, port)

    async def stop_server(self):
        self.stop_server_called = True

    async def connect_to_peer(self, ip, port, peer_id):
        self.connect_to_peer_called.append((ip, port, peer_id))

    async def send_message(self, peer_id, msg):
        self.send_message_called.append((peer_id, msg))


# Dummy Discovery Service simulating basic behavior.
class DummyDiscoveryService:
    def __init__(self):
        self.start_called = False
        self.allow_discovery = None
        self.stop_called = False

    async def start(self, allow_discovery):
        self.start_called = True
        self.allow_discovery = allow_discovery

    async def stop(self):
        self.stop_called = True


class TestP2PConnector(unittest.IsolatedAsyncioTestCase):
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
        # Create the P2PConnector instance.
        self.p2p = PeerConnectionManager(
            on_message_callback=AsyncMock(),
            client_id="client1",
            network_config=self.network_config,
            on_peer_disconnected=AsyncMock(),
            client_name="Tester",
            port=5000
        )
        # Replace dependent components with dummy ones.
        self.dummy_ws_connector = DummyWsConnector()
        self.dummy_discovery_service = DummyDiscoveryService()
        self.p2p.ws_connector = self.dummy_ws_connector
        self.p2p.discovery_service = self.dummy_discovery_service

    async def test_start(self):
        # Test that start() calls discovery_service.start and ws_connector.start_server.
        await self.p2p.start(host="127.0.0.1", port=6000, allow_discovery=True)
        self.assertTrue(self.dummy_discovery_service.start_called)
        self.assertEqual(self.dummy_discovery_service.allow_discovery, True)
        self.assertEqual(self.dummy_ws_connector.start_server_called, ("127.0.0.1", 6000))

    async def test_stop(self):
        # Test that stop() calls discovery_service.stop and ws_connector.stop_server.
        await self.p2p.stop()
        self.assertTrue(self.dummy_discovery_service.stop_called)
        self.assertTrue(self.dummy_ws_connector.stop_server_called)

    async def test_connect_to_peer(self):
        # Test that connect_to_peer() calls ws_connector.connect_to_peer.
        await self.p2p.connect_to_peer("192.168.1.2", 7000, "peer2")
        self.assertIn(("192.168.1.2", 7000, "peer2"), self.dummy_ws_connector.connect_to_peer_called)

    async def test_send_message(self):
        # Test that send_message() calls ws_connector.send_message.
        msg = {"type": "text", "text": "hello"}
        await self.p2p.send_message("peer2", msg)
        self.assertIn(("peer2", msg), self.dummy_ws_connector.send_message_called)

    async def test_on_peer_discovered_new_peer(self):
        # Test _on_peer_discovered: simulate a valid discovery message from a new peer.
        discovered_msg = {"client_id": "peer2", "port": 7000, "display_name": "Peer2"}
        addr = ("192.168.1.3", 1234)
        # Call the method (which schedules a task to connect to the peer)
        self.p2p._on_peer_discovered(discovered_msg, addr)
        # Allow scheduled task to run.
        await asyncio.sleep(0.1)
        # Check that the peer was added.
        self.assertIn("peer2", self.p2p.peers)
        peer_info = self.p2p.peers["peer2"]
        self.assertEqual(peer_info["ip"], "192.168.1.3")
        self.assertEqual(peer_info["port"], 7000)
        self.assertEqual(peer_info["display_name"], "Peer2")
        # Verify that connect_to_peer was called.
        self.assertIn(("192.168.1.3", 7000, "peer2"), self.dummy_ws_connector.connect_to_peer_called)

    async def test_on_peer_discovered_ignore_invalid(self):
        # Test that _on_peer_discovered ignores messages with missing client_id or self-discovery.
        # Case 1: Message with no client_id.
        msg_no_id = {"port": 7000, "display_name": "PeerX"}
        addr = ("192.168.1.4", 1234)
        self.p2p._on_peer_discovered(msg_no_id, addr)
        self.assertEqual(len(self.p2p.peers), 0)
        # Case 2: Message with client_id same as self.
        msg_self = {"client_id": "client1", "port": 7000, "display_name": "Self"}
        self.p2p._on_peer_discovered(msg_self, addr)
        self.assertNotIn("client1", self.p2p.peers)

    async def test_get_peers_list(self):
        # Manually set some peers and verify that get_peers_list returns the expected list.
        current_time = time.time()
        self.p2p.peers = {
            "peer1": {"display_name": "Alpha", "ip": "1.1.1.1", "port": 6000, "last_seen": current_time},
            "peer2": {"display_name": "Beta", "ip": "2.2.2.2", "port": 7000, "last_seen": current_time},
        }
        peers_list = self.p2p.get_peers_list()
        expected = [
            {"peer_id": "peer1", "display_name": "Alpha"},
            {"peer_id": "peer2", "display_name": "Beta"},
        ]
        self.assertCountEqual(peers_list, expected)


if __name__ == "__main__":
    unittest.main()
