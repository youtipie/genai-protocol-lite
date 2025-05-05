import socket

from dataclasses import dataclass
from typing import Optional

from AIConnector.common.exceptions import ParameterException


@dataclass
class Config:
    """
    Data class representing the Class network configuration settings.

    Attributes:
        webserver_port (Optional[int]): Port number for the webserver.
            If not provided, an available port within the autodiscovery range will be used.
            Required in: 'local' and 'remote'.
        azure_endpoint_url (Optional[str]): URL endpoint for Azure connectivity.
                                            Required in: 'remote'.
        azure_access_key (Optional[str]): Access key for Azure services.
                                          Required in: 'remote'.
        advertisement_port (int): Port used for network advertisement. Defaults to 9999.
                                  Required in: 'local' and 'remote'.
        advertisement_ip (str): IP address for network advertisement. Defaults to "224.1.1.1".
                                Required in: 'local' and 'remote'.
        advertisement_interval (float): Interval (in seconds) for sending advertisements. Defaults to 15.0.
                                        Required in: 'local' and 'remote'.
        heartbeat_delay (float): Delay (in seconds) between heartbeat messages. Defaults to 5.0.
                                 Required in: 'local' and 'remote'.
        webserver_port_min (int): Minimum port number for autodiscovery. Defaults to 5000.
                                                Required in: 'local'.
        webserver_port_max (int): Maximum port number for autodiscovery. Defaults to 7000.
                                                Required in: 'local'.
        peer_discovery_timeout (float): Timeout (in seconds) for peer discovery. Defaults to 30.0.
                                        Required in: 'local' and 'remote'.
        peer_ping_interval (float): Interval (in seconds) for pinging peers. Defaults to 5.0.
                                    Required in: 'local' and 'remote'.
        azure_api_version (str): API version for Azure communications. Defaults to "1.0".
                                 Required in: 'remote'.
        connection_type (str): Type of connection, either "local" or "remote". Defaults to "local".
                               Required in: 'local' and 'remote'.
    """
    webserver_port: Optional[int] = None

    azure_endpoint_url: Optional[str] = None
    azure_access_key: Optional[str] = None

    advertisement_port: int = 9999
    advertisement_ip: str = "224.1.1.1"
    advertisement_interval: float = 15.0
    heartbeat_delay: float = 15.0
    webserver_port_min: int = 5000
    webserver_port_max: int = 65000
    peer_discovery_timeout: float = 30.0
    peer_ping_interval: float = 5.0
    azure_api_version: str = "1.0"
    connection_type: str = "local"

    def __post_init__(self):
        """
        Validate the network configuration parameters immediately after initialization.

        Raises:
            ParameterException: If any parameter is invalid.
        """
        # Validate connection type
        if self.connection_type not in ("local", "remote"):
            raise ParameterException("Invalid connection type. Only 'local' and 'remote' are allowed.")

        # For remote connections, ensure Azure settings are provided
        if self.connection_type == "remote":
            if not (self.azure_endpoint_url and self.azure_access_key):
                raise ParameterException(
                    "Azure endpoint URL and access key must be provided for 'remote' sessions."
                )

        # Define a list of fields to validate (field name, value, expected type)
        fields_to_validate = (
            ("advertisement_port", self.advertisement_port, int),
            ("webserver_port_min", self.webserver_port_min, int),
            ("webserver_port_max", self.webserver_port_max, int),
            ("advertisement_interval", self.advertisement_interval, float),
            ("heartbeat_delay", self.heartbeat_delay, float),
            ("peer_discovery_timeout", self.peer_discovery_timeout, float),
            ("peer_ping_interval", self.peer_ping_interval, float),
        )

        # Check each field for correct type and positive value
        for field_name, value, expected_type in fields_to_validate:
            if not isinstance(value, expected_type):
                raise ParameterException(f"Parameter '{field_name}' must be of type {expected_type.__name__}.")
            if value <= 0:
                raise ParameterException(f"Parameter '{field_name}' must be greater than 0.")

        # Ensure autodiscovery port range is valid
        if self.webserver_port_min > self.webserver_port_max:
            raise ParameterException(
                "webserver_port_min cannot be greater than webserver_port_max."
            )

        # If webserver_port is not set, determine an available port from the autodiscovery range
        if not self.webserver_port:
            self.webserver_port = get_available_port(
                self.webserver_port_min,
                self.webserver_port_max
            )


@dataclass
class NetworkConfig(Config):
    """
    Data class representing the App network configuration settings.

    Attributes:
        client_id (Optional[str]): Identifier for the client.
                                   Required in: 'local' and 'remote'.
    """
    client_id: Optional[str] = None


def get_available_port(start_port: int = 5000, end_port: int = 7000) -> Optional[int]:
    """
    Find and return the first available network port in the given range (inclusive).

    The function iterates through the port range and attempts to bind a temporary
    socket to each port. If the bind is successful, the port is considered available.

    Args:
        start_port (int): The beginning of the port range to check. Defaults to 5000.
        end_port (int): The end of the port range to check. Defaults to 7000.

    Returns:
        Optional[int]: The first available port number, or None if no port is available.
    """
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                # Attempt to bind the socket to the current port on all interfaces.
                sock.bind(("0.0.0.0", port))
                # Successful bind indicates the port is free.
                return port
            except OSError:
                # Port is already in use; try the next one.
                continue
    # Return None if no available port is found in the specified range.
    return None
