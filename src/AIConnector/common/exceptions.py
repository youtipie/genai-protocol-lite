class ParameterException(ValueError):
    """Exception raised for errors in the input parameters."""
    pass


class PeerDisconnectedException(Exception):
    """Exception indicating that the peer has disconnected."""
    pass


class AgentConnectionError(Exception):
    """Exception indicating that we couldn't connect to agent."""
    pass
