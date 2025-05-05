import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from AIConnector.connector.ws_connector import WsConnector


# DummyWebSocket: used for tests that complete the iteration.
class DummyWebSocket:
    def __init__(self, messages=None, remote_address=("127.0.0.1", 12345)):
        self.messages = messages or []
        self.sent_messages = []
        self.remote_address = remote_address
        self.closed = False

    async def send(self, message):
        self.sent_messages.append(message)

    async def __aiter__(self):
        for msg in self.messages:
            yield msg

    def close(self):
        self.closed = True


# InfiniteDummyWebSocket: yields messages and then never terminates.
class InfiniteDummyWebSocket:
    def __init__(self, messages=None, remote_address=("127.0.0.1", 12345)):
        self._messages = messages or []
        self.sent_messages = []
        self.remote_address = remote_address
        self.closed = False

    async def send(self, message):
        self.sent_messages.append(message)

    async def __aiter__(self):
        for msg in self._messages:
            yield msg
        # Prevent termination of iteration.
        await asyncio.Future()

    def close(self):
        self.closed = True


# DummyServer for start_server/stop_server tests.
class DummyServer:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return


class TestWsConnector(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client_id = "client1"
        self.client_name = "Tester"
        self.on_message_callback = AsyncMock()
        self.on_peer_disconnected = AsyncMock()
        self.ws_connector = WsConnector(
            client_id=self.client_id,
            on_message_callback=self.on_message_callback,
            on_peer_disconnected=self.on_peer_disconnected,
            client_name=self.client_name
        )

    async def test_start_server(self):
        dummy_server = DummyServer()

        async def fake_serve(handler, host, port, ssl):
            return dummy_server

        with patch("connector.ws_connector.websockets.serve", new=fake_serve):
            await self.ws_connector.start_server(host="0.0.0.0", port=5000)
            self.assertIs(self.ws_connector.server, dummy_server)

    async def test_stop_server(self):
        dummy_server = DummyServer()
        self.ws_connector.server = dummy_server
        await self.ws_connector.stop_server()
        self.assertTrue(dummy_server.closed)

    async def test_handler_valid_messages(self):
        # Use an infinite dummy WebSocket so that the connection remains active.
        hello_msg = json.dumps({"type": "HELLO", "from_id": "peerX"})
        text_msg = json.dumps({"type": "text", "text": "hello", "from_id": "peerX"})
        infinite_ws = InfiniteDummyWebSocket(messages=[hello_msg, text_msg])
        # Run _handler in a background task.
        handler_task = asyncio.create_task(self.ws_connector._handler(infinite_ws, path="/"))
        # Allow time for the HELLO message to be processed.
        await asyncio.sleep(0.1)
        # on_message_callback should have been called twice.
        self.assertEqual(self.on_message_callback.await_count, 2)
        # The HELLO message should have registered "peerX".
        self.assertIn("peerX", self.ws_connector.active_connections)
        # Clean up by cancelling the handler task.
        handler_task.cancel()
        try:
            await handler_task
        except asyncio.CancelledError:
            pass

    async def test_handler_invalid_json(self):
        invalid_msg = "not a json"
        dummy_ws = DummyWebSocket(messages=[invalid_msg])
        await self.ws_connector._handler(dummy_ws, path="/")
        self.on_message_callback.assert_not_awaited()

    async def test_client_handler_and_disconnect(self):
        hello_msg = json.dumps({"type": "HELLO", "from_id": "peerY"})
        text_msg = json.dumps({"type": "text", "text": "client hello", "from_id": "peerY"})
        dummy_ws = DummyWebSocket(messages=[hello_msg, text_msg])
        # Pre-add the connection for peerY.
        self.ws_connector.active_connections["peerY"] = dummy_ws
        await self.ws_connector._client_handler(dummy_ws, "peerY")
        # on_message_callback should have been called for both messages.
        self.assertEqual(self.on_message_callback.await_count, 2)
        # on_peer_disconnected should be called after disconnection.
        self.on_peer_disconnected.assert_awaited_with("peerY")
        self.assertNotIn("peerY", self.ws_connector.active_connections)

    async def test_send_message_success(self):
        dummy_ws = DummyWebSocket()
        self.ws_connector.active_connections["peerZ"] = dummy_ws
        msg = {"type": "text", "text": "hello"}
        await self.ws_connector.send_message("peerZ", msg)
        self.assertEqual(len(dummy_ws.sent_messages), 1)
        sent = json.loads(dummy_ws.sent_messages[0])
        self.assertEqual(sent, msg)

    async def test_send_message_no_connection(self):
        try:
            await self.ws_connector.send_message("nonexistent", {"type": "text", "text": "hello"})
        except Exception as e:
            self.fail(f"send_message raised an exception unexpectedly: {e}")

    async def test_connect_to_peer(self):
        dummy_ws = DummyWebSocket()
        with patch("connector.ws_connector.websockets.connect", new=AsyncMock(return_value=dummy_ws)):
            await self.ws_connector.connect_to_peer("127.0.0.1", 8000, "peerA")
            self.assertIn("peerA", self.ws_connector.active_connections)
            self.assertEqual(len(dummy_ws.sent_messages), 1)
            handshake = json.loads(dummy_ws.sent_messages[0])
            self.assertEqual(handshake.get("type"), "HELLO")
            self.assertEqual(handshake.get("from_id"), self.client_id)
            self.assertEqual(handshake.get("from_name"), self.client_name)

    async def test_connect_to_peer_already_connected(self):
        dummy_ws = DummyWebSocket()
        self.ws_connector.active_connections["peerA"] = dummy_ws
        with patch("connector.ws_connector.websockets.connect", new=AsyncMock()) as mock_connect:
            await self.ws_connector.connect_to_peer("127.0.0.1", 8000, "peerA")
            mock_connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
