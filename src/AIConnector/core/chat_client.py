import asyncio
import logging
import uuid
from typing import Optional, Dict, Any, List, Callable, Awaitable, Tuple

from AIConnector.common.message import MessageTypes
from AIConnector.common.network import NetworkConfig
from AIConnector.common.exceptions import PeerDisconnectedException, AgentConnectionError
from AIConnector.connector.peer_connection_manager import PeerConnectionManager
from .job_manager import JobManager
from .message_factory import MessageFactory

logger = logging.getLogger(__name__)


class ChatClient:
    """
    A peer-to-peer chat client that handles message exchange and job processing.
    """

    # Heartbeat timeout in seconds. If no heartbeat is received within this period,
    # the pending job future is resolved with a timeout message.
    _HEARTBEAT_TIMEOUT = 30

    def __init__(self, network_config: NetworkConfig, client_id: str, client_name: Optional[str] = None) -> None:
        """
        Initialize the ChatClient.

        Args:
            network_config (NetworkConfig): Network configuration settings.
            client_id (str): Unique identifier for the client.
            client_name (Optional[str]): Optional display name of the user.
        """
        self.client_id: str = client_id
        self.network_config: NetworkConfig = network_config
        self.client_name: str = client_name or "DefaultUser"
        self.connector: Optional[PeerConnectionManager] = None
        self.job_manager: JobManager = JobManager(send_message_callback=self.send_typed_message)
        self.pending_jobs_futures: Dict[str, asyncio.Future] = {}

        # Lists for storing async callbacks for peer events.
        self._peer_connected_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_disconnected_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_discovered_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self._peer_lost_callbacks: List[Callable[[str], Awaitable[None]]] = []

        self._timeout_task: Optional[asyncio.Task] = None

    async def start(self, host: str = "0.0.0.0") -> None:
        """
        Start the chat client by initializing the connector and job manager.

        Args:
            host (str): The host address to bind the server.
        """
        # Enable discovery if there are jobs to process.
        allow_discovery = bool(self.job_manager.job_list())

        self.connector = PeerConnectionManager(
            on_message_callback=self._on_message_received,
            on_peer_connected=self._on_peer_connected,
            on_peer_disconnected=self._on_peer_disconnected,
            on_peer_discovered=self._on_peer_discovered,
            on_peer_lost=self._on_peer_lost,
            client_name=self.client_name,
            client_id=self.client_id,
            network_config=self.network_config,
            port=self.network_config.webserver_port,
        )
        await self.connector.start(
            host=host,
            port=self.network_config.webserver_port,
            allow_discovery=allow_discovery
        )
        self.job_manager.start()
        logger.debug(f"[ChatClient] Started (client_id={self.client_id})")

        # Start background task to periodically check heartbeat timeouts.
        self._timeout_task = asyncio.create_task(self._check_future_timeouts())

    async def stop(self) -> None:
        """
        Stop the chat client, including the connector and job manager.
        """
        if self.connector:
            await self.connector.stop()
            logger.debug("[ChatClient] Connector stopped")
        if self.job_manager:
            await self.job_manager.stop()
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
        logger.debug("[ChatClient] Stopped")

    async def msg_type_hello(self, msg: Dict[str, Any]) -> None:
        """
        Handle a HELLO message.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        from_id: str = msg.get("from_id")
        logger.debug(f"[ChatClient] Received HELLO from {from_id}")

    async def msg_type_text(self, msg: Dict[str, Any]) -> None:
        """
        Handle a TEXT message.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        peer_id: str = msg.get("from_id")
        text: str = msg.get("text", "")
        queue_id: str = msg.get("queue_id", "")
        # Process the text message via the job manager.
        await self.job_manager.process_message(msg=text, from_id=peer_id, queue_id=queue_id)
        logger.debug(f"[ChatClient] Client {self.client_id} received text: {text}")

    async def msg_job_list(self, msg: Dict[str, Any]) -> List[Any]:
        """
        Return the current job list.

        Args:
            msg (Dict[str, Any]): The received message (unused).

        Returns:
            List[Any]: The list of registered jobs.
        """
        return self.job_manager.job_list()

    async def msg_job_unknown(self, msg: Dict[str, Any]) -> None:
        """
        Handle an unknown message type.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        msg_type: str = msg.get("type")
        logger.debug(f"[ChatClient] Unknown message type: {msg_type}")

    async def msg_final_message(self, msg: Dict[str, Any]) -> None:
        """
        Process a FINAL_MESSAGE by resolving the corresponding job future.

        Args:
            msg (Dict[str, Any]): The message containing the final result.
        """
        logger.debug(f"[ChatClient] Final message received: {msg}")
        queue_id: str = msg.get("queue_id")
        text: str = msg.get("text")
        fut: Optional[asyncio.Future] = self.pending_jobs_futures.get(queue_id)
        if fut and not fut.done():
            fut.set_result(text)

        logger.debug(f"[ChatClient] Final message processed for job_id={queue_id}, result={text}")

    async def msg_system_message(self, msg: Dict[str, Any]) -> None:
        """
        Handle a SYSTEM_MESSAGE.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        logger.debug(f"[ChatClient] System message received: {msg}")

    async def msg_heartbeat(self, msg: Dict[str, Any]) -> None:
        """
        Handle a HEARTBEAT message, updating heartbeat timestamps for associated futures.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        logger.debug(f"[ChatClient] Heartbeat received: {msg}")
        peer_id = msg.get("from_id")
        current_time = asyncio.get_event_loop().time()
        for fut in self.pending_jobs_futures.values():
            if getattr(fut, "peer_id", None) == peer_id:
                fut.heartbeat = current_time

    async def msg_error(self, msg: Dict[str, Any]) -> None:
        """
        Handle an ERROR message by resolving the corresponding future with an error message.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        logger.error(f"[ChatClient] Error message received: {msg}")
        queue_id: str = msg.get("queue_id")
        fut: Optional[asyncio.Future] = self.pending_jobs_futures.get(queue_id)
        if fut and not fut.done():
            fut.set_result("error")


    async def _on_message_received(self, msg: Dict[str, Any]) -> None:
        """
        Dispatch incoming messages to the appropriate handler based on the message type.

        Args:
            msg (Dict[str, Any]): The received message.
        """
        # Map message types to their corresponding handlers.
        fns: Dict[str, Callable[[Dict[str, Any]], asyncio.Future]] = {
            MessageTypes.HELLO.value: self.msg_type_hello,
            MessageTypes.TEXT.value: self.msg_type_text,
            MessageTypes.JOB_LIST.value: self.msg_job_list,
            MessageTypes.FINAL_MESSAGE.value: self.msg_final_message,
            MessageTypes.SYSTEM_MESSAGE.value: self.msg_system_message,
            MessageTypes.HEARTBEAT.value: self.msg_heartbeat,
            MessageTypes.ERROR.value: self.msg_error,
        }
        msg_type: str = msg.get("type", "").lower()
        # Default to TEXT handler if the message type is not found.
        fn = fns.get(msg_type, self.msg_type_text)
        await fn(msg=msg)

    async def _on_peer_connected(self, peer_id: str) -> None:
        """
        Handle actions when a new peer connects.

        Args:
            peer_id (str): The identifier of the connected peer.
        """
        logger.debug(f"[ChatClient] Peer connected: {peer_id}")
        for callback in self._peer_connected_callbacks:
            await callback(peer_id)

    async def _on_peer_disconnected(self, peer_id: str) -> None:
        """
        Handle cleanup when a peer disconnects, including canceling pending jobs.

        Args:
            peer_id (str): The identifier of the disconnected peer.
        """
        logger.debug(f"[ChatClient] Peer disconnected: {peer_id}")
        for job_id, fut in list(self.pending_jobs_futures.items()):
            if getattr(fut, "peer_id", None) == peer_id:
                if not fut.done():
                    fut.set_exception(PeerDisconnectedException(f"Task {job_id} canceled: peer {peer_id} disconnected"))
                del self.pending_jobs_futures[job_id]
        for callback in self._peer_disconnected_callbacks:
            await callback(peer_id)

    async def _on_peer_discovered(self, peer_id: str) -> None:
        """
        Handle actions when a new peer is discovered.

        Args:
            peer_id (str): The identifier of the discovered peer.
        """
        for callback in self._peer_discovered_callbacks:
            await callback(peer_id)

    async def _on_peer_lost(self, peer_id: str) -> None:
        """
        Handle actions when a peer is lost.

        Args:
            peer_id (str): The identifier of the lost peer.
        """
        for callback in self._peer_lost_callbacks:
            await callback(peer_id)

    async def get_peers_list(self) -> List[Dict[str, Any]]:
        """
        Retrieve the list of connected peers.

        Returns:
            List[Dict[str, Any]]: A list of peer information dictionaries.
        """
        if self.connector is None:
            return []
        return self.connector.get_peers_list()

    async def get_peers_by_client_name(self, target_client_name: str) -> List[Dict[str, Any]]:
        """
        Retrieve peers matching the given display name.

        Args:
            target_client_name (str): The display name to search for.

        Returns:
            List[Dict[str, Any]]: A list of matching peer information dictionaries.
        """
        peers: List[Dict[str, Any]] = await self.get_peers_list()
        return [peer for peer in peers if peer["display_name"] == target_client_name]

    async def wait_all_peers(self, interval: float = 5, timeout: float = 30) -> List[Dict[str, Any]]:
        """
        Wait until at least one peer is discovered.

        Args:
            interval (float): Time interval between checks in seconds.
            timeout (float): Maximum time to wait in seconds.

        Returns:
            List[Dict[str, Any]]: A list of peer information dictionaries.

        Raises:
            TimeoutError: If no peer is discovered within the timeout period.
        """
        start_time = asyncio.get_event_loop().time()
        while True:
            peers = await self.get_peers_list()
            if peers:
                return peers
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"Couldn't find any peers within {timeout} seconds")
            await asyncio.sleep(interval)

    async def wait_for_peers(self, target_client_name: str, interval: float = 5, timeout: float = 30) -> Dict[str, Any]:
        """
        Wait until a peer with the given display name is found.

        Args:
            target_client_name (str): The display name to search for.
            interval (float): Time interval between checks in seconds.
            timeout (float): Maximum time to wait in seconds.

        Returns:
            Dict[str, Any]: The information dictionary for the first matching peer.

        Raises:
            TimeoutError: If no matching peer is found within the timeout period.
        """
        start_time = asyncio.get_event_loop().time()
        while True:
            peers = await self.get_peers_by_client_name(target_client_name=target_client_name)
            if peers:
                return peers[0]
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"Couldn't find {target_client_name} within {timeout} seconds")
            await asyncio.sleep(interval)

    async def send_typed_message(
        self,
        peer_id: str,
        text: str,
        message_type: str = MessageTypes.TEXT.value,
        job_id: Optional[str] = None,
        *args,
        **kwargs
    ) -> None:
        """
        Send a message with a specific type using the MessageFactory.

        Args:
            peer_id (str): The target peer's identifier.
            text (str): The message text.
            message_type (str): The type of the message.
            job_id (Optional[str]): Optional job identifier.
            *args: Additional positional arguments for MessageFactory.
            **kwargs: Additional keyword arguments for MessageFactory.
        """
        message_factory = MessageFactory(
            message_type=message_type,
            from_id=self.client_id,
            job_id=job_id,
            *args,
            **kwargs
        )
        await self._send_message(peer_id=peer_id, msg=message_factory.generate_message(text=text))

    async def send_message(self, peer_id: str, text: str) -> str:
        """
        Send a TEXT message to a specific peer and create a pending job.

        Args:
            peer_id (str): The target peer's identifier.
            text (str): The message text.

        Returns:
            str: A unique queue/job identifier.
        """
        queue_id: str = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        # Attach metadata to the future for heartbeat monitoring.
        future.peer_id = peer_id
        current_time = loop.time()
        future.created_at = current_time
        future.heartbeat = current_time
        self.pending_jobs_futures[queue_id] = future

        message_factory = MessageFactory(
            message_type=MessageTypes.TEXT.value,
            from_id=self.client_id,
            queue_id=queue_id,
        )
        await self._send_message(peer_id=peer_id, msg=message_factory.generate_message(text=text))
        return queue_id

    async def wait_for_result(self, job_id: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """
        Wait for the result of a job identified by job_id.

        Args:
            job_id (str): The job identifier.
            timeout (Optional[float]): Optional timeout in seconds.

        Returns:
            str: The result text.

        Raises:
            ValueError: If no pending future is found for the job_id.
            asyncio.TimeoutError: If the result is not received within the timeout.
        """
        fut = self.pending_jobs_futures.get(job_id)
        if not fut:
            raise ValueError(f"No pending future for job_id={job_id}")
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            return True, result
        except PeerDisconnectedException:
            return False, "Peer disconnected"
        except AgentConnectionError:
            return False, "couldn't connect to Agent"

    async def _send_message(self, peer_id: str, msg: Dict[str, Any]) -> None:
        """
        Send a message to a peer using the underlying connector.

        Args:
            peer_id (str): The target peer's identifier.
            msg (Dict[str, Any]): The message payload.
        """
        await self.connector.send_message(peer_id, msg)

    async def register_job(self, job_call_back: Callable) -> None:
        """
        Register a new job callback with the job manager.

        Args:
            job_call_back (Callable): The callback function to register.
        """
        self.job_manager.register_job(job_call_back=job_call_back)

    def register_on_peer_connected_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback for when a peer connects.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer_id.
        """
        if callback not in self._peer_connected_callbacks:
            self._peer_connected_callbacks.append(callback)

    def register_on_peer_disconnected_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback for when a peer disconnects.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer_id.
        """
        if callback not in self._peer_disconnected_callbacks:
            self._peer_disconnected_callbacks.append(callback)

    def register_on_peer_discovered_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback for when a peer is discovered.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer_id.
        """
        if callback not in self._peer_discovered_callbacks:
            self._peer_discovered_callbacks.append(callback)

    def register_on_peer_lost_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Register an async callback for when a peer is lost.

        Args:
            callback (Callable[[str], Awaitable[None]]): Async function accepting a peer_id.
        """
        if callback not in self._peer_lost_callbacks:
            self._peer_lost_callbacks.append(callback)

    async def _check_future_timeouts(self) -> None:
        """
        Periodically check all pending futures. If the time since the last heartbeat exceeds
        _HEARTBEAT_TIMEOUT seconds, resolve the future with a timeout message and remove it.
        """
        while True:
            try:
                current_time = asyncio.get_event_loop().time()
                for job_id, fut in list(self.pending_jobs_futures.items()):
                    if not fut.done():
                        last_hb = getattr(fut, "heartbeat", None)
                        if last_hb is not None and (current_time - last_hb > self._HEARTBEAT_TIMEOUT):
                            del self.pending_jobs_futures[job_id]
                            fut.set_exception(AgentConnectionError)
            except Exception as e:
                logger.error(f"[ChatClient] Error in _check_future_timeouts: {e}")
            await asyncio.sleep(5)

    async def close_connection(self, peer_id: str):
        """
        Close connection

        Args:
           peer_id (str): Unique identifier of the lost peer.
       """
        await self.connector.close_connection(peer_id=peer_id)
