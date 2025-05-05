from abc import ABC, abstractmethod


class BaseDiscoveryService(ABC):
    """
    Abstract base class for discovery services.

    Subclasses must implement methods to start and stop the discovery service.
    """

    @abstractmethod
    def start(self, allow_discovery: bool = False) -> None:
        """
        Start the discovery service.

        Args:
            allow_discovery (bool, optional): Flag indicating whether peer discovery is enabled.
                Defaults to False.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the discovery service.
        """
        pass
