import pickle
from queue import Empty

import websockets
from .generator_process import Generator
from .generator_process.actor import ActorContext
import asyncio

generator = Generator(ActorContext.BACKEND)


async def handle_msg_from_client(websocket):
    stopped = False
    print("Client connected")

    async def send_response():
        while not stopped:
            try:
                msg = generator._response_queue.get(block=False)
                if msg:
                    await websocket.send(pickle.dumps(msg))
            except Empty as _:
                pass
            await asyncio.sleep(0.1)

    async def receive_msg():
        print("Waiting for messages")
        async for msg in websocket:
            msg = pickle.loads(msg)
            print("unpacked", msg)
            generator._receive(msg)
            print("handle msg done")

        nonlocal stopped
        stopped = True

    await asyncio.gather(
        send_response(),
        receive_msg()
    )

    print("Client disconnected")


async def main():
    port = 9765
    async with websockets.serve(handle_msg_from_client, "localhost", port):
        print("Server listening on port ", port)
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
