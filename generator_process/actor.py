import enum
import pickle
import traceback
import threading
from threading import Lock
from queue import Queue, Empty
from typing import Type, TypeVar, Generator
import site
import sys
import os

from ..absolute_path import absolute_path
from .future import Future
import asyncio


def _load_dependencies():
    site.addsitedir(absolute_path(".python_dependencies"))
    deps = sys.path.pop(-1)
    sys.path.insert(0, deps)
    if sys.platform == 'win32':
        # fix for ImportError: DLL load failed while importing cv2: The specified module could not be found.
        # cv2 needs python3.dll, which is stored in Blender's root directory instead of its python directory.
        python3_path = os.path.abspath(os.path.join(sys.executable, "..\\..\\..\\..\\python3.dll"))
        if os.path.exists(python3_path):
            os.add_dll_directory(os.path.dirname(python3_path))


_load_dependencies()


# if current_process().name == "__actor__":
#     _load_dependencies()

class ActorContext(enum.IntEnum):
    """
    The context of an `Actor` object.
    
    One `Actor` instance is the `FRONTEND`, while the other instance is the backend, which runs in a separate process.
    The `FRONTEND` sends messages to the `BACKEND`, which does work and returns a result.
    """
    FRONTEND = 0
    BACKEND = 1


class Message:
    """
    Represents a function signature with a method name, positonal arguments, and keyword arguments.

    Note: All arguments must be picklable.
    """

    def __init__(self, method_name, args, kwargs):
        self.method_name = method_name
        self.args = args
        self.kwargs = kwargs

    CANCEL = "__cancel__"
    END = "__end__"

    def __str__(self):
        return f"Message(method_name={self.method_name}, args={self.args}, kwargs={self.kwargs})"


def _start_backend(cls, message_queue, response_queue):
    cls(
        ActorContext.BACKEND,
        message_queue=message_queue,
        response_queue=response_queue
    ).start()


class TracedError(BaseException):
    def __init__(self, base: BaseException, trace: str):
        self.base = base
        self.trace = trace


T = TypeVar('T', bound='Actor')


class Actor:
    """
    Base class for specialized actors.
    
    Uses queues to send actions to a background process and receive a response.
    Calls to any method declared by the frontend are automatically dispatched to the backend.

    All function arguments must be picklable.
    """

    _message_queue: Queue
    _response_queue: Queue
    _lock: Lock

    _shared_instance = None

    # Methods that are not used for message passing, and should not be overridden in `_setup`.
    _protected_methods = {
        "start",
        "close",
        "is_alive",
        "can_use",
        "shared",
        "set_svr_uri"
    }

    def __init__(self, context: ActorContext, message_queue: Queue = None, response_queue: Queue = None):
        self.context = context
        self._message_queue = message_queue if message_queue is not None else Queue(maxsize=1)
        self._response_queue = response_queue if response_queue is not None else Queue(maxsize=1)
        self._setup()
        self.__class__._shared_instance = self
        self.svr_connected = False
        self.svr_uri = None
        self.work_thread = None
        self.svr_close = False

    def _setup(self):
        """
        Setup the Actor after initialization.
        """
        match self.context:
            case ActorContext.FRONTEND:
                self._lock = Lock()
                for name in filter(lambda name: callable(getattr(self, name)) and not name.startswith(
                        "_") and name not in self._protected_methods, dir(self)):
                    setattr(self, name, self._send(name))
            case ActorContext.BACKEND:
                pass

    @classmethod
    def shared(cls: Type[T]) -> T:
        return cls._shared_instance or cls(ActorContext.FRONTEND).start()

    def start(self: T) -> T:
        """
        Start the actor process.
        """
        match self.context:
            case ActorContext.FRONTEND:
                # self.process = get_context('spawn').Process(target=_start_backend, args=(self.__class__, self._message_queue, self._response_queue), name="__actor__", daemon=True)
                # self.process.start()
                self.work_thread = threading.Thread(target=self._client_to_sever, daemon=True)
                self.work_thread.start()
            case ActorContext.BACKEND:
                os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
                self.work_thread = threading.Thread(target=self._backend_loop, daemon=True)
                self.work_thread.start()
        return self

    def set_svr_uri(self, uri):
        print("set_svr_uri", uri)
        self.svr_uri = uri

    def _client_to_sever(self):
        from dream_textures.protocol import generator_service_pb2, generator_service_pb2_grpc
        import grpc

        self.svr_close = False
        self.svr_connected = False

        async def send_msg_to_svr(stub, msg):
            dumps = pickle.dumps(msg)

            # chunk dumps by 1MB
            chunk_size = 1024 * 1024
            chunks = []

            for i in range(0, len(dumps), chunk_size):
                chunks.append(generator_service_pb2.MsgPickleDumps(content=dumps[i:i + chunk_size]))

            resp_chunks = []
            async for response in stub.CallRemoteMethod(chunks):
                if response:
                    if response.is_chunked:
                        resp_chunks.append(response.content)
                    else:
                        if len(resp_chunks) > 0 and len(response.content) == 0:
                            resp_chunks.append(response.content)
                            response = pickle.loads(b''.join(resp_chunks))
                        else:
                            response = pickle.loads(response.content)

                        self._response_queue.put(response)

        async def new_connect(uri):
            connect_closed = False

            print("start connect to", uri)
            while not self.svr_close and not connect_closed and uri == self.svr_uri:
                try:
                    async with grpc.aio.insecure_channel(uri) as channel:
                        try:
                            await asyncio.wait_for(channel.channel_ready(), timeout=1.0)
                        except asyncio.TimeoutError as _:
                            continue
                        print("connected to", uri)
                        stub = generator_service_pb2_grpc.GeneratorServiceStub(channel)

                        async def poll_send_msg():
                            while not self.svr_close and not connect_closed:
                                try:
                                    msg = self._message_queue.get(block=False)
                                    if msg:
                                        await send_msg_to_svr(stub, msg)
                                except Empty as _:
                                    pass
                                await asyncio.sleep(0.1)

                            print("poll_send_msg quit")

                        async def close_when_uri_change():
                            while not self.svr_close:
                                # print("close_when_uri_change", uri, self.svr_uri)
                                if uri != self.svr_uri:
                                    break
                                await asyncio.sleep(0.2)
                            await channel.close(grace=1)
                            nonlocal connect_closed
                            connect_closed = True
                            self.svr_connected = False
                            print("channel closed")

                        self.svr_connected = True

                        await asyncio.gather(
                            poll_send_msg(),
                            close_when_uri_change()
                        )
                        print("disconnected from", uri)

                except Exception as e:
                    print(e)
                    await asyncio.sleep(0.2)

        async def main():
            while not self.svr_close:
                print("svr_uri", self.svr_uri)
                if self.svr_uri:
                    await new_connect(self.svr_uri)
                await asyncio.sleep(0.2)

        asyncio.run(main())

    def close(self):
        """
        Stop the actor process.
        """
        match self.context:
            case ActorContext.FRONTEND:
                # self.process.terminate()
                self.svr_close = True
                if self.work_thread:
                    self.work_thread.join()
                # self._message_queue.close()
                # self._response_queue.close()
            case ActorContext.BACKEND:
                pass

    @classmethod
    def shared_close(cls: Type[T]):
        if cls._shared_instance is None:
            return
        cls._shared_instance.close()
        cls._shared_instance = None
        print("shared_close finished")

    def is_alive(self):
        match self.context:
            case ActorContext.FRONTEND:
                return self.svr_connected
            case ActorContext.BACKEND:
                return True

    def can_use(self):
        if result := self._lock.acquire(blocking=False):
            self._lock.release()
        return result

    def _backend_loop(self):
        while True:
            self._receive(self._message_queue.get())

    def _receive(self, message: Message):
        try:
            response = getattr(self, message.method_name)(*message.args, **message.kwargs)
            if isinstance(response, Generator):
                for res in iter(response):
                    extra_message = None
                    try:
                        extra_message = self._message_queue.get(block=False)
                    except:
                        pass
                    if extra_message == Message.CANCEL:
                        break
                    if isinstance(res, Future):
                        def check_cancelled():
                            try:
                                return self._message_queue.get(block=False) == Message.CANCEL
                            except:
                                return False

                        res.check_cancelled = check_cancelled
                        res.add_response_callback(lambda _, res: self._response_queue.put(res))
                        res.add_exception_callback(lambda _, e: self._response_queue.put(RuntimeError(repr(e))))
                        res.add_done_callback(lambda _: None)
                    else:
                        self._response_queue.put(res)
            else:
                self._response_queue.put(response)
        except Exception as e:
            print(e)
            trace = traceback.format_exc()
            try:
                if sys.modules[e.__module__].__file__.startswith(absolute_path(".python_dependencies")):
                    e = RuntimeError(repr(e))
                    # might be more suitable to have specific substitute exceptions for cases
                    # like torch.cuda.OutOfMemoryError for frontend handling in the future
            except (AttributeError, KeyError) as ee:
                print("something wrong with exception module", ee)
                pass
            print("put traced error in queue")
            self._response_queue.put(TracedError(e, trace))

        # print("put end in queue")
        self._response_queue.put(Message.END)

        # print("recv done", message.method_name)

    def _send(self, name):
        def _send(*args, _block=False, **kwargs):
            future = Future()

            def _send_thread(future: Future):
                self._lock.acquire()
                self._message_queue.put(Message(name, args, kwargs))

                while not future.done:
                    if future.cancelled:
                        self._message_queue.put(Message.CANCEL)
                    response = self._response_queue.get()
                    if response == Message.END:
                        future.set_done()
                    elif isinstance(response, TracedError):
                        response.base.__cause__ = Exception(response.trace)
                        future.set_exception(response.base)
                    elif isinstance(response, Exception):
                        future.set_exception(response)
                    else:
                        future.add_response(response)

                self._lock.release()

            if _block:
                _send_thread(future)
            else:
                thread = threading.Thread(target=_send_thread, args=(future,), daemon=True)
                thread.start()
            return future

        return _send

    def __del__(self):
        self.close()
