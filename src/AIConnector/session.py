import asyncio
import uuid
import json
from typing import Any, Dict, Optional, Callable, Awaitable, List, Tuple
from AIConnector.common.logger import Logger
from AIConnector.common.exceptions import ParameterException
from AIConnector.common.network import NetworkConfig, get_available_port, Config
from AIConnector.core.chat_client import ChatClient


class Session:
    """
    Represents a session for a client. This class manages configuration, unique client ID generation,
    and initializes a ChatClient to handle peer-to-peer messaging.
    """

    FILENAME = "client_id.json"
    ALLOWED_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")

    def __init__(
        self,
        client_name: str,
        config: Config,
        client_id: Optional[str] = None,
        log_level: Optional[str] = "critical"
    ) -> None:
        """
        Initialize a new Session.

        Args:
            client_name (str): The display name of the client.
            config (Config): Network configuration settings.
            client_id (Optional[str]): Optional pre-defined client identifier.
            log_level (Optional[str]): Logging level. Defaults to "info".
        """
        self.client_name = client_name
        self.__config = config
        self.__client_id = client_id

        self.chat_client: Optional[ChatClient] = None

        # Callback lists for various peer events.
        self._peer_connected_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_disconnected_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_discovered_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_lost_callbacks: List[Callable[[str], Awaitable[None]]] = []

        self._send_lock = asyncio.Lock()

        if log_level.lower() not in self.ALLOWED_LOG_LEVELS:
            raise ParameterException(
                f"Invalid log level '{log_level}'. Allowed values: {self.ALLOWED_LOG_LEVELS}"
            )

        Logger(log_level=log_level)

    def __get_client_id(self) -> str:
        """
        Retrieve a unique client identifier from file, or generate and store a new one if necessary.

        Returns:
            str: The client identifier.
        """
        if self.__client_id:
            return self.__client_id

        try:
            with open(self.FILENAME, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}

        if stored_client_id := data.get(self.client_name):
            self.__client_id = stored_client_id
            return stored_client_id

        # Generate a new client ID if not found.
        new_id = str(uuid.uuid4())
        data[self.client_name] = new_id

        with open(self.FILENAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        self.__client_id = new_id
        return new_id

    @property
    def client_id(self) -> str:
        """
        Get the unique client identifier, generating it if needed.

        Returns:
            str: The client identifier.
        """
        if self.__client_id is None:
            self.__client_id = self.__get_client_id()
        return self.__client_id

    @property
    def config(self) -> NetworkConfig:
        """
        Retrieve the network configuration, ensuring the client_id is updated.

        Returns:
            NetworkConfig: The network configuration.
        """
        network_config = NetworkConfig(**self.__config.__dict__)
        network_config.client_id = self.client_id
        return network_config

    async def start(self, message_handler: Optional[Callable[[str], Awaitable[str]]] = None) -> None:
        """
        Start the session by initializing and starting the ChatClient.
        Optionally bind a message handler for incoming messages.

        Args:
            message_handler (Optional[Callable[[str], Awaitable[str]]]): Async function to process incoming messages.
        """
        self.chat_client = ChatClient(
            client_name=self.client_name,
            client_id=self.client_id,
            network_config=self.config
        )
        self._register_chat_client_on_peer_connected_callback()
        self._register_chat_client_on_peer_disconnected_callback()
        self._register_chat_client_on_peer_discovered_callback()
        self._register_chat_client_on_peer_lost_callback()

        if message_handler:
            await self.bind(message_handler)

        # Attempt to start the chat client; if the port is unavailable, assign a new one.
        while True:
            try:
                await self.chat_client.start()
                break
            except OSError:
                self.config.webserver_port = get_available_port(
                    self.config.webserver_port_min,
                    self.config.webserver_port_max
                )

    async def stop(self) -> None:
        """
        Stop the session by stopping the ChatClient.
        """
        await self.chat_client.stop()

    async def bind(self, handler: Callable[[str], Awaitable[str]]) -> None:
        """
        Bind a message handler to the ChatClient for processing incoming messages.

        Args:
            handler (Callable[[str], Awaitable[str]]): Async function that processes an incoming message.
        """
        if self.chat_client is None:
            raise Exception("ChatClient is not started yet. Call start() before binding a handler.")
        await self.chat_client.register_job(handler)

    async def send(self, target_client_name: str, text: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """
        Sends a message to a peer by display name and waits for a response.

        Args:
            target_client_name (str): The display name of the target peer.
            text (str): The message text to send.
            timeout (Optional[float], optional): The timeout in seconds for waiting for a response. Defaults to None.

        Returns:
            Tuple[bool, str]: A tuple where the first value indicates success (True if the message was sent successfully, False otherwise),
            and the second value contains the response text from the remote peer.
        """
        if self.chat_client is None:
            raise Exception("ChatClient is not started yet. Call start() before sending messages.")

        async with self._send_lock:
            # Wait for a peer with the specified display name.
            peer = await self.chat_client.wait_for_peers(
                target_client_name=target_client_name,
                timeout=self.config.peer_discovery_timeout,
                interval=self.config.peer_ping_interval,
            )
            if not peer:
                raise Exception(f"Peer '{target_client_name}' not found.")

            peer_id = peer["peer_id"]
            queue_id = await self.chat_client.send_message(peer_id, text)
            is_success, result = await self.chat_client.wait_for_result(queue_id, timeout=timeout)
            await self.chat_client.close_connection(peer_id)
            return is_success, result

    async def get_client_list(self, timeout: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieve a list of currently connected peers.

        Args:
            timeout (int): Maximum time to wait (in seconds) for peers.

        Returns:
            List[Dict[str, Any]]: A list of peer information dictionaries.
        """
        return await self.chat_client.wait_all_peers(timeout=timeout)

    def _register_chat_client_on_peer_connected_callback(self) -> None:
        """
        Register all stored peer-connected callbacks with the ChatClient.
        """
        for registered_callback in self._peer_connected_callbacks:
            self.chat_client.register_on_peer_connected_callback(callback=registered_callback)

    def _register_chat_client_on_peer_disconnected_callback(self) -> None:
        """
        Register all stored peer-disconnected callbacks with the ChatClient.
        """
        for registered_callback in self._peer_disconnected_callbacks:
            self.chat_client.register_on_peer_disconnected_callback(callback=registered_callback)

    def register_on_peer_connected_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback to be called when a peer connects.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer ID.
        """
        self._peer_connected_callbacks.append(callback)
        if self.chat_client is not None:
            self._register_chat_client_on_peer_connected_callback()

    def register_on_peer_disconnected_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback to be called when a peer disconnects.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer ID.
        """
        self._peer_disconnected_callbacks.append(callback)
        if self.chat_client is not None:
            self._register_chat_client_on_peer_disconnected_callback()

    def _register_chat_client_on_peer_discovered_callback(self) -> None:
        """
        Register all stored peer-discovered callbacks with the ChatClient.
        """
        for registered_callback in self._peer_discovered_callbacks:
            self.chat_client.register_on_peer_discovered_callback(callback=registered_callback)

    def _register_chat_client_on_peer_lost_callback(self) -> None:
        """
        Register all stored peer-lost callbacks with the ChatClient.
        """
        for registered_callback in self._peer_lost_callbacks:
            self.chat_client.register_on_peer_lost_callback(callback=registered_callback)

    def register_on_peer_discovered_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback to be called when a peer is discovered.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer ID.
        """
        self._peer_discovered_callbacks.append(callback)
        if self.chat_client is not None:
            self._register_chat_client_on_peer_discovered_callback()

    def register_on_peer_lost_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback to be called when a peer is lost.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer ID.
        """
        self._peer_lost_callbacks.append(callback)
        if self.chat_client is not None:
            self._register_chat_client_on_peer_lost_callback()
