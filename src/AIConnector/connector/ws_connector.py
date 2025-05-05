import asyncio
import json
import time
import logging

import websockets
from typing import Callable, Optional, Dict, Any

from AIConnector.connector.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class WsConnector(BaseConnector):
    """
    Manages WebSocket connections to peers.
    """

    def __init__(
        self,
        client_id: str,
        on_message_callback: Callable[[Dict[str, Any]], asyncio.Future],
        on_peer_connected: Optional[Callable[[str], asyncio.Future]] = None,
        on_peer_disconnected: Optional[Callable[[str], asyncio.Future]] = None,
        ssl_context: Optional[Any] = None,
        client_name: Optional[str] = None,
    ) -> None:
        """
        Initialize the WebSocket connector.

        Args:
            client_id (str): Unique identifier for this client.
            on_message_callback (Callable[[Dict[str, Any]], asyncio.Future]):
                Coroutine to be called with incoming messages.
            on_peer_connected (Optional[Callable[[str], asyncio.Future]], optional):
                Coroutine to be called when a peer connects.
            on_peer_disconnected (Optional[Callable[[str], asyncio.Future]], optional):
                Coroutine to be called when a peer disconnects.
            ssl_context (Optional[Any], optional): SSL context for secure connections.
            client_name (Optional[str], optional): Client name for identification.
        """
        self.client_id = client_id
        self.on_message_callback = on_message_callback
        self.on_peer_connected = on_peer_connected
        self.on_peer_disconnected = on_peer_disconnected
        self.ssl_context = ssl_context
        self.client_name = client_name

        # Dictionary to store active WebSocket connections by peer ID.
        self.active_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.server: Optional[websockets.server.Serve] = None

    async def start_server(
        self, host: str = "0.0.0.0", port: int = 5000, allow_discovery: bool = True
    ) -> None:
        """
        Start the WebSocket server.

        Args:
            host (str): The host address to bind the server.
            port (int): The port number to bind the server.
            allow_discovery (bool): If True, start the WebSocket server.
        """
        if not allow_discovery:
            return

        self.server = await websockets.serve(self._handler, host, port, ssl=self.ssl_context)
        logger.info(f"[WsConnector] WebSocket server started on {host}:{port}")

    async def stop_server(self) -> None:
        """
        Stop the WebSocket server and close all active connections.
        """
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("[WsConnector] Server stopped")

    async def _handler(self, websocket: websockets.WebSocketServerProtocol, path: str = "") -> None:
        """
        Handle incoming WebSocket connections.

        Args:
            websocket (websockets.WebSocketServerProtocol): The connected WebSocket.
            path (str): URL path (unused).
        """
        peername = websocket.remote_address
        logger.info(f"[WsServer] Connection established with {peername}")
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                except Exception as e:
                    logger.error(f"[WsServer] Error parsing message: {e}")
                    continue

                # Register connection upon receiving a HELLO message.
                if msg.get("type") == "HELLO":
                    peer_id = msg.get("from_id")
                    if peer_id:
                        self.active_connections[peer_id] = websocket
                        if self.on_peer_connected:
                            await self.on_peer_connected(peer_id)

                # Process the incoming message.
                await self.on_message_callback(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"[WsServer] Connection closed: {peername}")
        finally:
            # Remove connection from active connections and notify disconnection.
            for pid, ws in list(self.active_connections.items()):
                if ws == websocket:
                    del self.active_connections[pid]
                    if self.on_peer_disconnected:
                        await self.on_peer_disconnected(pid)
                    break

    async def connect_to_peer(self, ip: str, port: int, peer_id: str) -> None:
        """
        Connect to a peer using a WebSocket connection.

        Args:
            ip (str): IP address of the peer.
            port (int): Port number of the peer.
            peer_id (str): Unique identifier of the peer.
        """
        if peer_id in self.active_connections:
            return

        websocket_uri = f"ws://{ip}:{port}"
        try:
            websocket = await websockets.connect(websocket_uri, ssl=self.ssl_context)
            self.active_connections[peer_id] = websocket
            logger.info(f"[WsConnector] Connected to {peer_id} ({ip}:{port})")

            # Handle messages from the peer asynchronously.
            asyncio.create_task(self._client_handler(websocket, peer_id))

            # Send a handshake HELLO message.
            handshake_msg = {
                "type": "HELLO",
                "from_id": self.client_id,
                "from_name": self.client_name or "Unknown",
                "timestamp": time.time(),
            }
            await websocket.send(json.dumps(handshake_msg))
        except Exception as e:
            logger.error(f"[WsConnector] Connection error to {ip}:{port} - {e}")

    async def _client_handler(self, websocket: websockets.WebSocketClientProtocol, peer_id: str) -> None:
        """
        Handle messages received from a connected peer.

        Args:
            websocket (websockets.WebSocketClientProtocol): The peer's WebSocket connection.
            peer_id (str): Unique identifier of the peer.
        """
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                except Exception as e:
                    logger.error(f"[WsClient] Error parsing message: {e}")
                    continue

                # Update connection info on HELLO messages.
                if msg.get("type") == "HELLO":
                    p_id = msg.get("from_id")
                    if p_id:
                        self.active_connections[p_id] = websocket

                # Process the received message.
                await self.on_message_callback(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.error(f"[WsClient] Connection with {peer_id} closed")
        finally:
            if peer_id in self.active_connections:
                del self.active_connections[peer_id]
                if self.on_peer_disconnected:
                    await self.on_peer_disconnected(peer_id)

    async def send_message(self, peer_id: str, msg: Dict[str, Any]) -> None:
        """
        Send a message to a specific peer via an active WebSocket connection.

        Args:
            peer_id (str): Unique identifier of the peer.
            msg (Dict[str, Any]): The message payload as a dictionary.
        """
        websocket = self.active_connections.get(peer_id)
        if websocket:
            try:
                await websocket.send(json.dumps(msg))
            except Exception as e:
                logger.error(f"[WsConnector] Error sending message to {peer_id}: {e}")
            else:
                logger.info(f"[WsConnector] Message sent to {peer_id}")
        else:
            logger.info(f"[WsConnector] No active connection with: {peer_id}")


    async def disconnect_from_peer(self, peer_id: str) -> None:
        """
        Close websocket connection

        Args:
           peer_id (str): Unique identifier of the lost peer.
       """
        try:
            await self.active_connections[peer_id].close()
            logger.info(f"[WsConnector] Closed WebSocket connection: {peer_id=}")
        except Exception as e:
            logger.error(f"[WsConnector] Error while disconnecting from {peer_id=}: {e}")
