import asyncio
import time
import logging
from typing import Callable, Optional, Dict, Any, List, Tuple

from AIConnector.common.network import NetworkConfig
from AIConnector.connector.base_connector import BaseConnector
from AIConnector.connector.ws_connector import WsConnector
from AIConnector.connector.azure_connector import AzureConnector

from AIConnector.discovery.base_discovery_service import BaseDiscoveryService
from AIConnector.discovery.discovery_service import DiscoveryService
from AIConnector.discovery.azure_discovery_service import AzureDiscoveryService

logger = logging.getLogger(__name__)


class P2PMeta(type):
    """
    Metaclass for PeerConnectionManager that dynamically sets up the appropriate
    connector and discovery service based on the network configuration.
    """
    def __call__(cls, *args, **kwargs):
        # Create the instance using the default __call__ method.
        instance = super().__call__(*args, **kwargs)
        connection_type = instance.network_config.connection_type

        if connection_type == "local":
            # For local connections, use the WebSocket connector and local discovery service.
            instance.connector = WsConnector(
                on_message_callback=instance.on_message_callback,
                on_peer_disconnected=instance.on_peer_disconnected,
                ssl_context=instance.ssl_context,
                client_name=instance.client_name,
                client_id=instance.client_id,
            )
            instance.discovery_service = DiscoveryService(
                on_peer_discovered_callback=instance._on_peer_discovered,
                on_peer_lost=instance._on_peer_lost,
                client_name=instance.client_name,
                port=instance.port,
                network_config=instance.network_config
            )
        else:
            # For remote connections, use the Azure connector and Azure discovery service.
            instance.connector = AzureConnector(
                client_name=instance.client_name,
                client_id=instance.client_id,
                azure_endpoint_url=instance.network_config.azure_endpoint_url,
                azure_access_key=instance.network_config.azure_access_key,
                azure_api_version=instance.network_config.azure_api_version,
                on_message_callback=instance.on_message_callback,
                on_peer_disconnected=instance.on_peer_disconnected
            )
            instance.discovery_service = AzureDiscoveryService(
                client_name=instance.client_name,
                client_id=instance.client_id,
                azure_endpoint_url=instance.network_config.azure_endpoint_url,
                azure_access_key=instance.network_config.azure_access_key,
                azure_api_version=instance.network_config.azure_api_version,
                on_peer_discovered_callback=instance._on_peer_discovered,
                on_peer_lost=instance._on_peer_lost,
            )

        return instance


class PeerConnectionManager(metaclass=P2PMeta):
    """
    Handles peer-to-peer connectivity using WebSocket connections and a discovery service.

    The connector and discovery service used are determined dynamically based on the
    provided network configuration. For a local connection type, the connector uses
    WebSocket-based communication; otherwise, Azure-based implementations are used.
    """

    def __init__(
        self,
        on_message_callback: Callable[[Dict[str, Any]], None],
        client_id: str,
        network_config: NetworkConfig,
        on_peer_connected: Optional[Callable[[str], None]] = None,
        on_peer_disconnected: Optional[Callable[[str], None]] = None,
        on_peer_discovered: Optional[Callable[[str], None]] = None,
        on_peer_lost: Optional[Callable[[str], None]] = None,
        ssl_context: Any = None,
        client_name: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """
        Initialize the PeerConnectionManager.

        Args:
            on_message_callback (Callable[[Dict[str, Any]], None]):
                Function to call when a message is received.
            client_id (str): Unique identifier for this client.
            network_config (NetworkConfig): Network configuration object.
            on_peer_connected (Optional[Callable[[str], None]], optional):
                Function to call when a peer connects.
            on_peer_disconnected (Optional[Callable[[str], None]], optional):
                Function to call when a peer disconnects.
            on_peer_discovered (Optional[Callable[[str], None]], optional):
                Function to call when a new peer is discovered.
            on_peer_lost (Optional[Callable[[str], None]], optional):
                Function to call when a peer is lost.
            ssl_context (Any, optional): SSL context for secure connections.
            client_name (Optional[str], optional): Client name for identification.
            port (Optional[int], optional): Port number for discovery broadcasting.
        """
        self.on_message_callback = on_message_callback
        self.on_peer_connected = on_peer_connected
        self.on_peer_disconnected = on_peer_disconnected
        self.on_peer_discovered = on_peer_discovered
        self.on_peer_lost = on_peer_lost
        self.ssl_context = ssl_context
        self.client_name = client_name
        self.client_id = client_id
        self.network_config = network_config
        self.port = port

        self.connector: BaseConnector = None
        self.discovery_service: BaseDiscoveryService = None

        # Dictionary mapping peer_id to peer info.
        self.peers: Dict[str, Dict[str, Any]] = {}

    async def start(self, host: str, port: int, allow_discovery: bool) -> None:
        """
        Start the discovery service and the connector's server.

        Args:
            host (str): Host address to bind the WebSocket server.
            port (int): Port number to bind the WebSocket server.
            allow_discovery (bool): Enable or disable the discovery phase.
        """
        await self.discovery_service.start(allow_discovery=allow_discovery)
        await self.connector.start_server(host=host, port=port, allow_discovery=allow_discovery)
        logger.debug("[PeerConnectionManager] Started")

    async def stop(self) -> None:
        """
        Stop the discovery service and the connector's server.
        """
        await self.discovery_service.stop()
        await self.connector.stop_server()
        logger.debug("[PeerConnectionManager] Stopped")

    async def connect_to_peer(self, ip: str, port: int, peer_id: str) -> None:
        """
        Connect to a discovered peer.

        Args:
            ip (str): IP address of the peer.
            port (int): Port number of the peer.
            peer_id (str): Unique identifier of the peer.
        """
        await self.connector.connect_to_peer(ip, port, peer_id)
        if self.on_peer_connected:
            result = self.on_peer_connected(peer_id)
            if asyncio.iscoroutine(result):
                await result

    async def send_message(self, peer_id: str, msg: Dict[str, Any]) -> None:
        """
        Send a message to a specific peer.

        Args:
            peer_id (str): Unique identifier of the recipient peer.
            msg (Dict[str, Any]): Message content as a dictionary.
        """
        # If no active connection exists, try to establish one using stored peer info.
        if peer_id not in self.connector.active_connections:
            peer_info = self.peers.get(peer_id)
            if peer_info:
                await self.connect_to_peer(peer_info["ip"], peer_info["port"], peer_id)
            else:
                logger.error(f"[PeerConnectionManager] Cannot send message: peer {peer_id} not discovered")
                return
        await self.connector.send_message(peer_id, msg)

    async def _on_peer_discovered(self, msg: Dict[str, Any], addr: Tuple[str, int]) -> None:
        """
        Async callback triggered when a new peer is discovered.

        Args:
            msg (Dict[str, Any]): Message containing peer details.
            addr (Tuple[str, int]): Tuple with the peer's (IP, port) address.
        """
        peer_id = msg.get("client_id")
        # Ignore invalid peer IDs or self-discovery.
        if not peer_id or peer_id == self.client_id:
            return

        ip = addr[0]
        port = msg.get("port")
        name = msg.get("display_name", "Unknown")
        now = time.time()

        # Add or update the peer in the peers dictionary.
        if peer_id not in self.peers:
            self.peers[peer_id] = {
                "ip": ip,
                "port": port,
                "display_name": name,
                "last_seen": now,
            }
        else:
            self.peers[peer_id].update({
                "ip": ip,
                "port": port,
                "last_seen": now,
            })

        if self.on_peer_discovered:
            try:
                result = self.on_peer_discovered(peer_id)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"[PeerConnectionManager] Error in on_peer_discovered callback: {e}")

    async def _on_peer_lost(self, peer_id: str) -> None:
        """
        Async callback triggered when a peer is lost.

        Args:
            peer_id (str): Unique identifier of the lost peer.
        """
        removed = self.peers.pop(peer_id, None)

        if removed is not None:
            logger.debug(f"[PeerConnectionManager] Peer {peer_id} removed from peers list")

        if self.on_peer_lost:
            result = self.on_peer_lost(peer_id)
            if asyncio.iscoroutine(result):
                await result

    def get_peers_list(self) -> List[Dict[str, str]]:
        """
        Retrieve a list of discovered peers.

        Returns:
            List[Dict[str, str]]: A list of dictionaries, each containing 'peer_id' and 'display_name'.
        """
        result = [
            {"peer_id": pid, "display_name": info["display_name"]}
            for pid, info in self.peers.items()
        ]
        logger.info(f"[PeerConnectionManager] Get peers list returned {result}")
        return result

    async def close_connection(self, peer_id: str):
        """
        Close connection

        Args:
           peer_id (str): Unique identifier of the lost peer.
       """
        await self.connector.disconnect_from_peer(peer_id)
