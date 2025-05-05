import asyncio
import json
import logging
import time
from typing import Callable, Optional, Dict, Any

import websockets

from azure.messaging.webpubsubservice import WebPubSubServiceClient
from AIConnector.connector.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class AzureConnector(BaseConnector):
    """
    AzureConnector implements message exchange via Azure Web PubSub,
    similar to how WsConnector operates for local connections.
    """

    def __init__(
        self,
        client_id: str,
        on_message_callback: Callable[[Dict[str, Any]], Any],
        azure_endpoint_url: str,
        azure_access_key: str,
        azure_api_version: str,
        messaging_hub: str = "messaging_demo",
        reconnect_attempts: int = 2,
        client_name: Optional[str] = None,
        on_peer_disconnected: Optional[Callable[[str], Any]] = None,
        on_peer_connected: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """
        Initialize the AzureConnector.

        Args:
            client_id (str): Identifier for the client.
            on_message_callback (Callable[[Dict[str, Any]], Any]): Callback function to handle incoming messages.
            azure_endpoint_url (str): Azure Web PubSub endpoint URL.
            azure_access_key (str): Access key for Azure Web PubSub.
            azure_api_version (str): API version for Azure services.
            messaging_hub (str, optional): Name of the messaging hub. Defaults to "messaging_demo".
            reconnect_attempts (int, optional): Number of reconnection attempts on failure. Defaults to 2.
            client_name (Optional[str], optional): Name of the client. Defaults to None.
            on_peer_disconnected (Optional[Callable[[str], Any]], optional): Callback when a peer disconnects. Defaults to None.
            on_peer_connected (Optional[Callable[[str], Any]], optional): Callback when a peer connects. Defaults to None.
        """
        self.client_id = client_id
        self.on_message_callback = on_message_callback
        self.on_peer_disconnected = on_peer_disconnected
        self.on_peer_connected = on_peer_connected
        self.client_name = client_name
        self.reconnect_attempts = reconnect_attempts
        self.messaging_hub = messaging_hub

        self.is_connected = False
        self.running = False
        self.active_connections: Dict[str, websockets.WebSocketClientProtocol] = {}

        # Initialize the service client for the messaging hub.
        connection_string = f"Endpoint={azure_endpoint_url};AccessKey={azure_access_key};ApiVersion={azure_api_version}"
        self.service_client = WebPubSubServiceClient.from_connection_string(
            connection_string,
            hub=messaging_hub,
        )
        self.websocket = None

    async def start_server(self, host: str = None, port: int = None, allow_discovery: bool = False) -> None:
        """
        Establish a WebSocket connection with the messaging hub.

        The host and port parameters are provided for interface compatibility,
        but they are not used in AzureConnector.

        Args:
            host (str, optional): Not used in AzureConnector.
            port (int, optional): Not used in AzureConnector.
            allow_discovery (bool, optional): Not used in AzureConnector.
        """
        self.running = True
        try:
            logger.info(f"Client ID: {self.client_id}")
            token = self.service_client.get_client_access_token(user_id=self.client_id)
            self.websocket = await websockets.connect(token["url"])
            self.is_connected = True
            logger.info(f"[AzureConnector] Connected to Azure Web PubSub messaging hub: {self.messaging_hub}")

            # Start receiving messages asynchronously.
            asyncio.create_task(self._receive_messages())

        except Exception as e:
            logger.error(f"[AzureConnector] Connection failed: {e}")
            await self._attempt_reconnect()

    async def stop_server(self) -> None:
        """
        Stop the WebSocket connection with the messaging hub.
        """
        self.running = False
        self.is_connected = False
        if self.websocket:
            await self.websocket.close()
            logger.info("[AzureConnector] Messaging WebSocket connection closed")

    async def send_message(self, peer_id: str, msg: Dict[str, Any]) -> None:
        """
        Send a message to a specific peer via the messaging hub.

        Args:
            peer_id (str): The identifier of the target peer.
            msg (Dict[str, Any]): The message payload to send.
        """
        if not self.is_connected:
            logger.error("[AzureConnector] Cannot send message: not connected")
            return

        try:
            message = {
                "type": "MESSAGE",
                "from_id": self.client_id,
                "from_name": self.client_name or "Unknown",
                "to_id": peer_id,
                "timestamp": time.time(),
                "payload": msg,
            }
            # Send the message as a JSON string.
            self.service_client.send_to_user(peer_id, json.dumps(message))
        except Exception as e:
            logger.error(f"[AzureConnector] Error sending message to {peer_id}: {e}")
        else:
            logger.info(f"[AzureConnector] Message sent to {peer_id}")

    async def connect_to_peer(self, ip: str, port: int, peer_id: str) -> None:
        """
        For Azure, a direct connection to peers is not required.
        Instead, a HELLO message is sent to simulate a handshake.

        Args:
            ip (str): Not used in AzureConnector.
            port (int): Not used in AzureConnector.
            peer_id (str): The identifier of the peer to connect to.
        """
        hello_msg = {
            "type": "HELLO",
            "from_id": self.client_id,
            "from_name": self.client_name or "Unknown",
            "timestamp": time.time(),
        }
        await self.send_message(peer_id, hello_msg)

    async def _receive_messages(self) -> None:
        """
        Receive incoming messages via the messaging hub.
        """
        while self.running and self.websocket:
            try:
                message = await self.websocket.recv()
                msg = json.loads(message)
                # If the received message is a string, try to parse it again.
                if isinstance(msg, str):
                    msg = json.loads(msg)
                payload = msg["payload"]
                # If a HELLO message is received, update active connections and trigger callback.
                if payload.get("type").lower() == "hello":
                    peer_id = payload.get("from_id")
                    if peer_id:
                        self.active_connections[peer_id] = self.websocket
                        if self.on_peer_connected:
                            await self.on_peer_connected(peer_id)

                # Process the incoming message with the provided callback.
                await self.on_message_callback(payload)
            except websockets.exceptions.ConnectionClosed:
                logger.error("[AzureConnector] Messaging WebSocket connection closed")
                await self._attempt_reconnect()
                break
            except Exception as e:
                logger.error(f"[AzureConnector] Error processing message: {e}")

    async def _attempt_reconnect(self) -> None:
        """
        Attempt to reconnect to Azure Web PubSub after a connection loss.
        """
        for attempt in range(self.reconnect_attempts):
            try:
                logger.info(f"[AzureConnector] Reconnection attempt {attempt + 1}/{self.reconnect_attempts}")
                await self.start_server()
                if self.is_connected:
                    return
            except Exception as e:
                logger.error(f"[AzureConnector] Reconnection attempt failed: {e}")
            # Exponential backoff before the next attempt.
            await asyncio.sleep(2 ** attempt)
        logger.error("[AzureConnector] Failed to reconnect after multiple attempts")


    async def disconnect_from_peer(self, peer_id: str) -> None:
        """
        Close connection

        Args:
           peer_id (str): Unique identifier of the lost peer.
       """
        pass
