import asyncio
import logging
import random

from AIConnector.session import Session, NetworkConfig


async def message_handler(msg: str) -> str:
    await asyncio.sleep(random.randint(1, 10))
    return f"response on msg: {msg}"

async def on_peer_connected(peer_id: str):
    logging.info(f"Peer connected: {peer_id}")


async def on_peer_disconnected(peer_id: str):
    logging.info(f"Peer disconnected: {peer_id}")


async def on_peer_discovered(peer_id: str):
    logging.info(f"Peer discovered: {peer_id}")


async def on_peer_lost(peer_id: str):
    logging.info(f"Peer lost: {peer_id}")


async def main():
    session = Session(client_name="connection_agent", config=NetworkConfig(connection_type="local"), log_level='info')
    session.register_on_peer_connected_callback(callback=on_peer_connected)
    session.register_on_peer_disconnected_callback(callback=on_peer_disconnected)
    session.register_on_peer_discovered_callback(callback=on_peer_discovered)
    session.register_on_peer_lost_callback(callback=on_peer_lost)
    await session.start(message_handler=message_handler)

    logging.info("Local session started. Listening for incoming requests...")
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
