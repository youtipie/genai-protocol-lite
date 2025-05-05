import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from AIConnector.session import Session


class TestSession(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Create a temporary file for session persistence and pre-populate it with an empty JSON object.
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        Session.FILENAME = self.temp_file.name
        # Write an empty dictionary to avoid JSONDecodeError on read.
        with open(Session.FILENAME, "w", encoding="utf-8") as f:
            f.write("{}")
        self.temp_file.close()

    def tearDown(self):
        # Remove the temporary file after tests run.
        if os.path.exists(Session.FILENAME):
            os.remove(Session.FILENAME)

    def test_invalid_connection_type(self):
        # Should raise ValueError for an invalid connection type due to SessionMeta.
        with self.assertRaises(ValueError):
            Session(connection_type="invalid")

    def test_get_client_id_and_name_existing(self):
        # When both client_name and client_id are provided, they should be returned as is.
        session = Session(connection_type="local", client_name="Tester", client_id="12345")
        name, client_id = session.get_client_id_and_name()
        self.assertEqual(name, "Tester")
        self.assertEqual(client_id, "12345")

    def test_get_client_id_and_name_file_persistence(self):
        # First call should generate a new client ID/name and persist it in file.
        session = Session(connection_type="local")
        name1, client_id1 = session.get_client_id_and_name()
        self.assertTrue(name1.startswith("name_"))
        self.assertIsNotNone(client_id1)

        # A new session with the same client_name should pick up the stored ID.
        session2 = Session(connection_type="local", client_name=name1)
        name2, client_id2 = session2.get_client_id_and_name()
        self.assertEqual(name1, name2)
        self.assertEqual(client_id1, client_id2)

    def test_properties_config(self):
        # Provide custom configuration and verify all properties are returning correct values.
        custom_config = {
            "advertisement_port": 8888,
            "advertisement_ip": "230.0.0.1",
            "advertisement_interval": 20,
            "heartbeat_delay": 10,
            "peer_discovery_timeout": 40,
            "peer_ping_interval": 8,
            "webserver_autodiscovery_port_min": 6000,
            "webserver_autodiscovery_port_max": 6100,
            "webserver_port": 6050,
        }
        session = Session(connection_type="remote", client_name="Tester", client_id="12345", config=custom_config)
        self.assertEqual(session.advertisement_port, 8888)
        self.assertEqual(session.advertisement_ip, "230.0.0.1")
        self.assertEqual(session.advertisement_interval, 20)
        self.assertEqual(session.heartbeat_delay, 10)
        self.assertEqual(session.peer_discovery_timeout, 40)
        self.assertEqual(session.peer_ping_interval, 8)
        self.assertEqual(session.webserver_autodiscovery_port_min, 6000)
        self.assertEqual(session.webserver_autodiscovery_port_max, 6100)
        self.assertEqual(session.webserver_port, 6050)

        # Also verify the NetworkConfig object returned via config property.
        config_obj = session.config
        self.assertEqual(config_obj.advertisement_port, 8888)
        self.assertEqual(config_obj.advertisement_ip, "230.0.0.1")
        self.assertEqual(config_obj.advertisement_interval, 20)
        self.assertEqual(config_obj.heartbeat_delay, 10)
        self.assertEqual(config_obj.webserver_port, 6050)
        self.assertEqual(config_obj.client_id, "12345")

    async def test_start_and_bind_local(self):
        # For a local session, if a message handler is provided, bind should be called.
        class DummyChatClient:
            async def start(self, host="0.0.0.0"):
                self.started = True

            async def register_job(self, handler):
                self.registered_handler = handler

        # Patch ChatClient so that our dummy version is used.
        with patch("session.ChatClient", return_value=DummyChatClient()):
            session = Session(connection_type="local", client_name="Tester", client_id="12345")
            dummy_handler = AsyncMock()
            await session.start(message_handler=dummy_handler)
            chat_client = session.chat_client
            self.assertTrue(hasattr(chat_client, "started") and chat_client.started)
            # Check that the handler was bound.
            self.assertTrue(hasattr(chat_client, "registered_handler"))
            self.assertEqual(chat_client.registered_handler, dummy_handler)

    async def test_start_remote_without_bind(self):
        # For a remote session, even if a message handler is provided, bind should not be called.
        class DummyChatClient:
            async def start(self, host="0.0.0.0"):
                self.started = True

            async def register_job(self, handler):
                self.registered_handler = handler

        with patch("session.ChatClient", return_value=DummyChatClient()):
            session = Session(connection_type="remote", client_name="Tester", client_id="12345")
            dummy_handler = AsyncMock()
            await session.start(message_handler=dummy_handler)
            chat_client = session.chat_client
            self.assertTrue(hasattr(chat_client, "started") and chat_client.started)
            # In remote mode, register_job should not be invoked.
            self.assertFalse(hasattr(chat_client, "registered_handler"))

    async def test_bind_without_start(self):
        # Calling bind without starting the ChatClient should raise an Exception.
        session = Session(connection_type="local", client_name="Tester", client_id="12345")
        dummy_handler = AsyncMock()
        with self.assertRaises(Exception) as context:
            await session.bind(dummy_handler)
        self.assertIn("ChatClient is not started yet", str(context.exception))

    async def test_send_without_start(self):
        # Calling send before starting the ChatClient should raise an Exception.
        session = Session(connection_type="remote", client_name="Tester", client_id="12345")
        with self.assertRaises(Exception) as context:
            await session.send("Peer", "Hello", timeout=1)
        self.assertIn("ChatClient is not started yet", str(context.exception))

    async def test_send_peer_not_found(self):
        # Create a dummy ChatClient that returns no peer (i.e. None) for wait_for_peers.
        class DummyChatClient:
            async def start(self, host="0.0.0.0"):
                self.started = True

            async def wait_for_peers(self, target_client_name, timeout, interval):
                return None  # Simulate no peer found.

        with patch("session.ChatClient", return_value=DummyChatClient()):
            session = Session(connection_type="remote", client_name="Tester", client_id="12345")
            await session.start()
            with self.assertRaises(Exception) as context:
                await session.send("NonExistent", "Hello", timeout=1)
            self.assertIn("Peer 'NonExistent' not found", str(context.exception))

    async def test_get_client_list(self):
        # Dummy ChatClient with wait_all_peers implemented.
        class DummyChatClient:
            async def start(self, host="0.0.0.0"):
                self.started = True

            async def wait_all_peers(self, timeout):
                return [{"peer_id": "peer1", "display_name": "Tester"}]

        with patch("session.ChatClient", return_value=DummyChatClient()):
            session = Session(connection_type="remote", client_name="Tester", client_id="12345")
            await session.start()
            client_list = await session.get_client_list(timeout=1)
            self.assertEqual(client_list, [{"peer_id": "peer1", "display_name": "Tester"}])


if __name__ == "__main__":
    unittest.main()
