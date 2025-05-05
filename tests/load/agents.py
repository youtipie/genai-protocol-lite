import asyncio
import sys

from AIConnector.session import Session, Config


async def message_handler(i, msg: str) -> str:
    return f"Response from client {i} on message: {msg}"


async def create_session(i: int):
    session = Session(
        client_name=f"load_agent_{i}",
        log_level='info',
        client_id=f"load_agent_{i}",
        config=Config(
            webserver_port=6000 + i,
            connection_type="local",
        )
    )
    await session.start(message_handler=lambda msg: message_handler(i, msg))


async def main():
    i = sys.argv[1]
    await create_session(int(i))

    await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
