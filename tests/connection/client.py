import asyncio
import logging
import random
from http.client import responses

from AIConnector.session import Session, NetworkConfig


async def on_peer_connected(peer_id: str):
    logging.info(f"Peer connected: {peer_id}")


async def on_peer_disconnected(peer_id: str):
    logging.info(f"Peer disconnected: {peer_id}")


async def on_peer_discovered(peer_id: str):
    logging.info(f"Peer discovered: {peer_id}")


async def on_peer_lost(peer_id: str):
    logging.info(f"Peer lost: {peer_id}")


async def send_message(session, client: str, msg: str):
    await asyncio.sleep(random.randint(1, 3))
    result = await session.send(client, msg)
    print(msg, result)


async def main():
    session = Session(
        client_name="connection_client",
        log_level='info',
        config=NetworkConfig(connection_type="local"),
    )
    session.register_on_peer_connected_callback(callback=on_peer_connected)
    session.register_on_peer_disconnected_callback(callback=on_peer_disconnected)
    session.register_on_peer_discovered_callback(callback=on_peer_discovered)
    session.register_on_peer_lost_callback(callback=on_peer_lost)

    for i in range(0, 10):
        asyncio.create_task(send_message(session, client="connection_agent", msg=f"Hello {i}"))
    # response = await session.send("connection_agent", "message from client")
    # logging.info(f"response: {response}")
    await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
