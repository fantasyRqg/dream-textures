from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class MsgPickleDumps(_message.Message):
    __slots__ = ("content", "is_chunked")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_CHUNKED_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    is_chunked: bool
    def __init__(self, content: _Optional[bytes] = ..., is_chunked: bool = ...) -> None: ...
