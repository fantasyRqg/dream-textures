import logging
import os
import pickle
from queue import Empty
from typing import Iterable

from .generator_process import Generator
from .generator_process.actor import ActorContext, Message
import asyncio
from .protocol import generator_service_pb2, generator_service_pb2_grpc
import grpc

generator = Generator(ActorContext.BACKEND)
generator.start()

chunk_size = 1024 * 1024


async def _chunked_response_generator(dumps):
    for i in range(0, len(dumps), chunk_size):
        yield generator_service_pb2.MsgPickleDumps(content=dumps[i:i + chunk_size], is_chunked=True)

    yield generator_service_pb2.MsgPickleDumps(content=b'', is_chunked=False)


class Server(generator_service_pb2_grpc.GeneratorServiceServicer):
    async def CallRemoteMethod(self,
                               request_iter: Iterable[generator_service_pb2.MsgPickleDumps],
                               context: grpc.ServicerContext
                               ) -> Iterable[generator_service_pb2.MsgPickleDumps]:
        content_list = []

        async for req in request_iter:
            content_list.append(req.content)

        msg = pickle.loads(b''.join(content_list))
        print("CallRemoteMethod", msg.method_name)
        generator._message_queue.put(msg)

        done = False
        while not done:
            try:
                response = generator._response_queue.get(block=False)
                if response is not None:
                    if response == Message.END:
                        done = True

                    dumps = pickle.dumps(response)

                    if len(dumps) > chunk_size:
                        async for chunk in _chunked_response_generator(dumps):
                            yield chunk
                    else:
                        yield generator_service_pb2.MsgPickleDumps(content=dumps, is_chunked=False)
            except Empty as _:
                await asyncio.sleep(0.1)


async def main():
    port = 9765

    if "DREAM_TEXTURES_SERVER_PORT" in os.environ:
        port = int(os.environ["DREAM_TEXTURES_SERVER_PORT"])

    svr = grpc.aio.server()
    generator_service_pb2_grpc.add_GeneratorServiceServicer_to_server(Server(), svr)
    listen_addr = f"0.0.0.0:{port}"
    svr.add_insecure_port(listen_addr)
    print(f"Listening on {listen_addr}")
    await svr.start()
    try:
        await svr.wait_for_termination()
    except KeyboardInterrupt as _:
        pass
    finally:
        await svr.stop(None)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
