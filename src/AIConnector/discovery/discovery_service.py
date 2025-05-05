import asyncio
import json
import socket
import struct
import time
import logging
from typing import Callable, Tuple, Dict, Any, Optional

from AIConnector.common.network import NetworkConfig

logger = logging.getLogger(__name__)


class DiscoveryProtocol(asyncio.DatagramProtocol):
    """
    Datagram protocol for handling UDP discovery messages.
    """

    def __init__(self, on_message_callback: Callable[[Dict[str, Any], Tuple[str, int]], None]) -> None:
        """
        Initialize the protocol with a callback for processing received messages.

        Args:
            on_message_callback: Callback function invoked with the parsed message and sender's address.
        """
        self.on_message_callback = on_message_callback

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        Process an incoming UDP datagram.

        Args:
            data: The received data as bytes.
            addr: A tuple containing the sender's IP address and port.
        """
        try:
            msg = json.loads(data.decode("utf-8"))
            # Process only DISCOVERY messages with a valid client_id.
            if msg.get("type") == "DISCOVERY" and msg.get("client_id"):
                asyncio.create_task(self.on_message_callback(msg, addr))
        except Exception as e:
            logger.debug(f"[DiscoveryProtocol] UDP parsing error: {e}")


class DiscoveryService:
    """
    Service for broadcasting and listening for peer discovery messages using multicast UDP.

    This service supports events for when peers appear (are discovered) and when peers are lost.
    """

    _PEER_DISAPPEAR_TIMEOUT = 30  # Seconds after which a peer is considered lost.

    def __init__(
            self,
            on_peer_discovered_callback: Callable[[Dict[str, Any], Tuple[str, int]], None],
            client_name: str,
            port: int,
            network_config: NetworkConfig,
            on_peer_lost: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Initialize the DiscoveryService.

        Args:
            on_peer_discovered_callback: Callback invoked when a peer is discovered.
            client_name: Display name of the client.
            port: Port number used by the service.
            network_config: Network configuration settings.
            on_peer_lost: Optional callback invoked when a peer is lost.
        """
        self.on_peer_discovered_callback = on_peer_discovered_callback
        self.on_peer_lost_callback = on_peer_lost

        self.transport: Optional[asyncio.DatagramTransport] = None
        self.running: bool = False
        self.client_name: str = client_name
        self.network_config: NetworkConfig = network_config
        self.port: int = port

        # Store peer information: key is client_id, value is a dict with last_seen timestamp and message data.
        self.peers: Dict[str, Dict[str, Any]] = {}

        self._cleanup_task: Optional[asyncio.Task] = None

    @staticmethod
    def get_socket(advertisement_port: int, advertisement_ip: str) -> socket.socket:
        """
        Create and configure a multicast UDP socket.

        Args:
            advertisement_port: The port to bind for receiving multicast messages.
            advertisement_ip: The multicast IP address.

        Returns:
            A configured, non-blocking UDP socket.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        sock.bind(("", advertisement_port))
        mreq = struct.pack("4sl", socket.inet_aton(advertisement_ip), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)
        return sock

    async def start(self, allow_discovery: bool = True) -> None:
        """
        Start the discovery service and begin periodic announcements.

        Args:
            allow_discovery: If True, the service actively announces and listens for discovery messages.
        """
        self.running = True

        loop = asyncio.get_event_loop()
        sock = self.get_socket(
            self.network_config.advertisement_port,
            self.network_config.advertisement_ip,
        )

        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(self._process_discovery_message),
            sock=sock
        )
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_peers())

        if allow_discovery:
            asyncio.create_task(self._periodic_announce())

    async def stop(self) -> None:
        """
        Stop the discovery service and close the underlying transport.
        """
        self.running = False
        if self.transport:
            self.transport.close()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _periodic_announce(self) -> None:
        """
        Periodically send discovery messages via multicast.
        """
        while self.running:
            try:
                msg = {
                    "type": "DISCOVERY",
                    "client_id": self.network_config.client_id,
                    "display_name": self.client_name,
                    "port": self.port,
                }
                encoded = json.dumps(msg).encode("utf-8")
                self.transport.sendto(
                    encoded,
                    (
                        self.network_config.advertisement_ip,
                        self.network_config.advertisement_port,
                    )
                )
            except Exception as e:
                logger.debug(f"[DiscoveryService] Sending error: {e}")
            await asyncio.sleep(self.network_config.advertisement_interval)

    async def _process_discovery_message(self, msg: Dict[str, Any], addr: Tuple[str, int]) -> None:
        """
        Process an incoming discovery message.

        Updates the last_seen timestamp for peers and invokes the on_peer_discovered_callback.

        Args:
            msg: The parsed discovery message.
            addr: The sender's address.
        """
        peer_id = msg.get("client_id")
        if not peer_id:
            return

        # Update or add peer information.
        self.peers[peer_id] = {
            "last_seen": time.time(),
            "msg": msg,
            "addr": addr,
        }

        if self.on_peer_discovered_callback:
            try:
                result = self.on_peer_discovered_callback(msg, addr)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"[DiscoveryService] Error in on_peer_discovered_callback: {e}")

    async def _cleanup_stale_peers(self) -> None:
        """
        Periodically check the list of discovered peers.

        If a peer's last update is older than _PEER_DISAPPEAR_TIMEOUT seconds,
        it is considered lost and removed, triggering the on_peer_lost_callback.
        """
        while self.running:
            try:
                now = time.time()
                stale_peers = [
                    peer_id for peer_id, info in self.peers.items()
                    if now - info.get("last_seen", now) > self._PEER_DISAPPEAR_TIMEOUT
                ]
                for peer_id in stale_peers:
                    del self.peers[peer_id]
                    if self.on_peer_lost_callback:
                        try:
                            result = self.on_peer_lost_callback(peer_id)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"[DiscoveryService] Error in on_peer_lost callback: {e}")
            except Exception as e:
                logger.error(f"[DiscoveryService] Error in _cleanup_stale_peers: {e}")
            await asyncio.sleep(1)
