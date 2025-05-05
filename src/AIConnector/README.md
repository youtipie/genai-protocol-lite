# Multi-Agent Communication Library

This library provides a unified, session-based API for building distributed multi-agent communication systems. It
supports two connection modes:

- **Local Mode:** Uses UDP/WebSocket for local communication.
- **Remote Mode:** Uses Azure Pub/Sub for cloud-based messaging.

The `Session` class is the main entry point, allowing agents to start a session, send messages to peers, and process
incoming messages asynchronously.

## Features

- **Dual Connection Modes:**
  - **Local Mode:** Communication using UDP/WebSocket.
  - **Remote Mode:** Communication via Azure Pub/Sub.
- **Session Management:**
  Persistent client identification with an optional display name.
- **Asynchronous Messaging:**
  Send requests to other clients and wait for their responses.
- **Custom Workload Processing:**
  Easily bind your own asynchronous message handler to process incoming requests.
- **Flexible Configuration:**
  Advanced settings available via the `config` parameter.

## Installation

```bash
  python pip install multi-agent-communication-library
```

## Usage Examples

### Agent Example (Providing Services)

This example demonstrates an agent that provides a service. The agent binds a custom asynchronous message handler to
process incoming requests with an abstract workload.

```python
import asyncio
from library.session import Session

async def process(message: str) -> str:
    # Simulate an abstract workload (e.g., data processing or computation)
    print(f"Processing workload for message: {message}")
    await asyncio.sleep(2)  # Simulate time-consuming work
    return f"Processed result for: {message}"

async def main():
    # Create a session in local mode (use "remote" for Azure Pub/Sub mode)
    session = Session(
        connection_type="local",
        client_name="worker_agent"
    )
    # Start the session with the message handler bound to process incoming requests
    await session.start(message_handler=process)
    # Keep the agent running indefinitely to process incoming tasks
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
```

### Client Example (Using Services)

This example shows a client that sends a task request to a service provider identified by its `client_name`.

```python
import asyncio

from library.session import Session

async def main():
    session = Session(
        connection_type="local",
        client_name="client"
    )
    await session.start()
    request = "Ipsum tempor ut adipisicing do magna ut excepteur deserunt non irure veniam dolore."
    result = await session.send("scrapper", request)
    print("Result:", result)
if __name__ == '__main__':
    asyncio.run(main())

```

## API Reference

### `Session` Class

#### Constructor

- **connection_type:**
  - `'local'` – Uses UDP/WebSocket for local communication.
  - `'remote'` – Uses Azure Pub/Sub for remote communication.
- **client_name:** Optional display name for the client.
- **client_id:** Optional unique identifier; if not provided, one will be generated.
- **config:** Optional configuration dictionary for advanced settings.
- **log_level:** Logging level (default is `'info'`).

#### Methods

- **`async start(message_handler: Optional[Callable[[str], Awaitable[str]]] = None) -> None`**
  Starts the session. If a `message_handler` is provided (for local mode), it will be bound to process incoming
  messages.
- **`async send(target_client_name: str, text: str, timeout: Optional[float] = None) -> str`**
  Sends a message to a peer identified by `target_client_name` and waits for a response


## Configuration Parameters

| Parameter                | Type            | Default Value | Description                                                                                        | Required In       |
|--------------------------|-----------------|---------------|----------------------------------------------------------------------------------------------------|-------------------|
| `webserver_port`         | `Optional[int]` | `None`        | Port number for the webserver. If not set, an available port from the autodiscovery range is used. | `local`           |
| `azure_endpoint_url`     | `Optional[str]` | `None`        | URL endpoint for Azure connectivity.                                                               | `remote`          |
| `azure_access_key`       | `Optional[str]` | `None`        | Access key for Azure services.                                                                     | `remote`          |
| `advertisement_port`     | `int`           | `9999`        | Port used for network advertisement.                                                               | `local`           |
| `advertisement_ip`       | `str`           | `"224.1.1.1"` | IP address for network advertisement.                                                              | `local`           |
| `advertisement_interval` | `float`         | `15.0`        | Interval (in seconds) for sending advertisements.                                                  | `local`, `remote` |
| `heartbeat_delay`        | `float`         | `5.0`         | Delay (in seconds) between heartbeat messages.                                                     | `local`, `remote` |
| `webserver_port_min`     | `int`           | `5000`        | Minimum port number for autodiscovery.                                                             | `local`           |
| `webserver_port_max`     | `int`           | `65000`       | Maximum port number for autodiscovery.                                                             | `local`           |
| `peer_discovery_timeout` | `float`         | `30.0`        | Timeout (in seconds) for peer discovery.                                                           | `local`, `remote` |
| `peer_ping_interval`     | `float`         | `5.0`         | Interval (in seconds) for pinging peers.                                                           | `local`, `remote` |
| `azure_api_version`      | `str`           | `"1.0"`       | API version for Azure communications.                                                              | `remote`          |
| `connection_type`        | `str`           | `"local"`     | Type of connection, either `"local"` or `"remote"`.                                                | `local`, `remote` |

### Notes:
- For **remote** connections, `azure_endpoint_url` and `azure_access_key` are required.
- If `webserver_port` is not set, it will be selected from the range [`webserver_port_min`, `webserver_port_max`].
- `connection_type` must be either `"local"` or `"remote"`.

## Customization

- **Message Handler:**
  Provide your own asynchronous function to process incoming messages. This function should accept a string message and
  return an awaitable string result.
- **Configuration Options:**
  Use the `config` parameter in the `Session` constructor for advanced settings.
