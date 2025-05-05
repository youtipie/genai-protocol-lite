import asyncio
import random
import sys
import threading

from AIConnector.session import Session, Config

file_lock = threading.Lock()


def log(msg):
    """Thread-safe file writing"""
    with file_lock:  # Ensures only one thread writes at a time
        with open("output.txt", "a") as file:
            file.write(f'{msg}\n')


async def message_handler(i, msg: str) -> str:
    return f"Response from client {i} on message: {msg}"


async def create_session(i):
    session = Session(
        client_name=f"load_client_{i}",
        log_level='info',
        client_id=f"load_client_{i}",
        config=Config(webserver_port=4444, connection_type="local", )
    )
    await session.start()

    agents = await session.get_client_list()

    for j in range(0, 5):
        target = random.choice(agents)
        response = await session.send(target["display_name"], f"message {j} from client {i} ")
        print(response)
        log(response)


async def main():
    i = sys.argv[1]
    await create_session(int(i))


if __name__ == '__main__':
    asyncio.run(main())
