from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseConnector(ABC):
    """
    Abstract base class for network connectors.

    Classes inheriting from BaseConnector must implement the methods
    to start and stop the server, as well as to send messages.
    """

    @abstractmethod
    async def start_server(self, host: str, port: int, allow_discovery: bool) -> None:
        """
        Start the server and establish necessary connections.

        Args:
            host (str): The host address to bind the server.
            port (int): The port number to bind the server.
            allow_discovery (bool): Flag indicating if discovery is allowed.
        """
        pass

    @abstractmethod
    async def stop_server(self) -> None:
        """
        Stop the server and close all active connections.
        """
        pass

    @abstractmethod
    async def send_message(self, peer_id: str, msg: Dict[str, Any]) -> None:
        """
        Send a message to a specified peer.

        Args:
            peer_id (str): Identifier of the target peer.
            msg (Dict[str, Any]): The message payload to be sent.
        """
        pass

    @abstractmethod
    async def disconnect_from_peer(self, peer_id: str) -> None:
        """
        Disconnect from peer by peer id

        Args:
            peer_id (str): Identifier of the target peer.
        """
        pass
