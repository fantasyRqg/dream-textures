import websockets
import asyncio
import pickle
import os

os.environ["DREAM_TEXTURES_SERVER"] = "1"

from dream_textures.generator_process.actor import Message


if __name__ == '__main__':
    async def hello():
        # uri = "ws://localhost:9765"
        uri = "ws://localhost:9765"
        async with websockets.connect(uri) as websocket:
            for i in range(10):
                await websocket.send(pickle.dumps(
                    Message(
                        method_name="load_mfasdfaodel",
                        args={"model_name": "ffhq-256", "fa": {"fad": i}},
                        kwargs={}
                    )
                ))
                d = await websocket.recv()
                await asyncio.sleep(0.2)
            # print(d)
    asyncio.run(hello())