import asyncio
import json
import logging
import time
import websockets
from typing import Callable, Optional, Dict, Any, Tuple

from azure.messaging.webpubsubservice import WebPubSubServiceClient
from AIConnector.common.exceptions import ParameterException
from AIConnector.discovery.base_discovery_service import BaseDiscoveryService

logger = logging.getLogger(__name__)


class AzureDiscoveryService(BaseDiscoveryService):
    """
    Service for peer discovery via Azure Web PubSub.

    This service functions similarly to the UDP-based DiscoveryService,
    but uses Azure for sending and receiving DISCOVERY messages.
    """

    def __init__(
            self,
            on_peer_discovered_callback: Optional[Callable[[Dict[str, Any], Tuple[str, int]], None]] = None,
            on_peer_lost: Optional[Callable[[Dict[str, Any], Tuple[str, int]], None]] = None,
            client_id: Optional[str] = None,
            client_name: Optional[str] = None,
            azure_endpoint_url: str = None,
            azure_access_key: str = None,
            azure_api_version: str = "1.0",
            discovery_hub: str = "discovery_demo",
            discovery_interval: float = 10,
            heartbeat_interval: float = 10,
    ) -> None:
        """
        Initialize the discovery service.

        Args:
            on_peer_discovered_callback: Callback invoked when a peer is discovered.
            on_peer_lost: Callback invoked when a peer is lost.
            client_id: Unique identifier of the client.
            client_name: Display name of the client.
            azure_endpoint_url: Azure Web PubSub endpoint URL (must start with "http://" or "https://").
            azure_access_key: Azure access key.
            azure_api_version: Azure API version.
            discovery_hub: Name of the discovery hub.
            discovery_interval: Interval (in seconds) for sending DISCOVERY messages.
            heartbeat_interval: Interval (in seconds) for cleaning up stale peer entries.
        """
        if not azure_endpoint_url or not azure_endpoint_url.startswith(("http://", "https://")):
            raise ParameterException(
                f"Invalid azure_endpoint_url: {azure_endpoint_url}. It must start with 'http://' or 'https://'."
            )
        self.azure_endpoint_url = azure_endpoint_url
        self.azure_access_key = azure_access_key
        self.azure_api_version = azure_api_version
        self.discovery_hub = discovery_hub
        self.discovery_interval = discovery_interval
        self.heartbeat_interval = heartbeat_interval

        self.on_peer_discovered_callback = on_peer_discovered_callback
        self.on_peer_lost_callback = on_peer_lost
        self.client_id = client_id
        self.client_name = client_name

        self.running = False
        self.allow_discovery = False
        self.discovered_peers: Dict[str, Dict[str, Any]] = {}

        # Initialize the service client for the discovery hub.
        self.service_client = WebPubSubServiceClient.from_connection_string(
            f"Endpoint={self.azure_endpoint_url};AccessKey={self.azure_access_key};ApiVersion={self.azure_api_version}",
            hub=self.discovery_hub,
        )
        self.websocket = None
        self._receive_task: Optional[asyncio.Task] = None
        self._announce_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self, allow_discovery: bool = True) -> None:
        """
        Start the discovery service by establishing a WebSocket connection with the discovery hub
        and starting background tasks for receiving DISCOVERY messages and periodic announcements.

        Args:
            allow_discovery: If True, enables peer discovery.
        """
        self.running = True
        self.allow_discovery = allow_discovery
        try:
            token = self.service_client.get_client_access_token()
            self.websocket = await websockets.connect(token["url"])
            logger.info(f"[AzureDiscoveryService] Connected to Azure Web PubSub discovery hub: {self.discovery_hub}")

            if allow_discovery:
                self._announce_task = asyncio.create_task(self._periodic_announce())
                logger.info("[AzureDiscoveryService] Azure Discovery Service started with peer discovery enabled")
            else:
                logger.info("[AzureDiscoveryService] Azure Discovery Service started with peer discovery disabled")

            self._cleanup_task = asyncio.create_task(self._cleanup_stale_peers())
            self._receive_task = asyncio.create_task(self._receive_messages())
        except Exception as e:
            logger.error(f"[AzureDiscoveryService] Discovery Service connection failed: {e}")

    async def stop(self) -> None:
        """
        Stop the discovery service and clean up resources.
        """
        self.running = False
        if self._receive_task:
            self._receive_task.cancel()
        if self._announce_task:
            self._announce_task.cancel()
        if self.websocket:
            await self.websocket.close()
        self.discovered_peers.clear()
        logger.info("[AzureDiscoveryService] Azure Discovery Service stopped")

    async def _receive_messages(self) -> None:
        """
        Receive incoming DISCOVERY messages and update the list of discovered peers.
        """
        while self.running and self.websocket:
            try:
                message = await self.websocket.recv()
                msg = json.loads(message)
                if isinstance(msg, str):
                    msg = json.loads(msg)
                peer_id = msg.get("client_id")
                # Process DISCOVERY messages from other peers.
                if msg.get("type") == "DISCOVERY" and peer_id != self.client_id:
                    if peer_id:
                        result_msg = {
                            "timestamp": msg.get("timestamp", 0),
                            "display_name": msg.get("client_name", "Unknown"),
                            "client_id": peer_id,
                            "metadata": msg.get("metadata", {})
                        }
                        self.discovered_peers[peer_id] = result_msg
                        if self.on_peer_discovered_callback:
                            # Use a dummy address since Azure does not provide a peer's IP.
                            dummy_addr = ("0.0.0.0", 0)
                            try:
                                result = self.on_peer_discovered_callback(result_msg, dummy_addr)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                logger.error(f"[DiscoveryService] Error in on_peer_discovered_callback: {e}")
            except websockets.exceptions.ConnectionClosed:
                logger.error("[AzureDiscoveryService] Discovery WebSocket connection closed")
                break
            except Exception as e:
                logger.error(f"[AzureDiscoveryService] Error processing discovery message: {e}")

    async def _periodic_announce(self) -> None:
        """
        Periodically send DISCOVERY messages through the discovery hub.
        """
        while self.running:
            try:
                discovery_msg = {
                    "type": "DISCOVERY",
                    "client_id": self.client_id,
                    "client_name": self.client_name or "Unknown",
                    "timestamp": time.time(),
                }
                self.service_client.send_to_all(json.dumps(discovery_msg))
            except Exception as e:
                logger.error(f"[AzureDiscoveryService] Error sending discovery message: {e}")
            else:
                logger.info("[AzureDiscoveryService] Discovery message sent")
            await asyncio.sleep(self.discovery_interval)

    async def _cleanup_stale_peers(self) -> None:
        """
        Periodically clean up stale peer entries.
        A peer is considered stale if its timestamp is older than 3 times the heartbeat_interval.
        """
        while self.running:
            try:
                current_time = asyncio.get_event_loop().time()
                stale_threshold = current_time - (self.heartbeat_interval * 3)

                stale_peers = [
                    peer_id for peer_id, info in self.discovered_peers.items()
                    if info["timestamp"] < stale_threshold
                ]

                for peer_id in stale_peers:
                    del self.discovered_peers[peer_id]
                    if self.on_peer_lost_callback:
                        try:
                            result = self.on_peer_lost_callback(peer_id)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"[DiscoveryService] Error in on_peer_disappear callback: {e}")

                    logger.debug(f"[AzureDiscoveryService] Removed stale peer: {peer_id}")

            except Exception as e:
                logger.error(f"[AzureDiscoveryService] Error in cleanup task: {e}")

            await asyncio.sleep(self.heartbeat_interval)
