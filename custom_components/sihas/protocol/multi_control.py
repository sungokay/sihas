"""HA-independent SiHAS FC25 command framing and acknowledgement validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..errors import PacketSizeError, ResponsePidMismatchError

CommandPairs = tuple[tuple[int, int], ...]


class CommandResponseError(Exception):
    """The FC25 response does not acknowledge the submitted command."""


def _unsigned(value: int, bits: int) -> None:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"Expected an unsigned {bits}-bit integer")


@dataclass(frozen=True)
class CommandMetadata:
    """Configured identity; wire constraints apply only when building an FC25 request."""

    mac: bytes
    device_type: int
    config: int


def _transform(body: bytes, context: datetime) -> bytes:
    seed = context.isoweekday() % 7 * 10000 + context.hour * 100 + context.minute
    mask = []
    for index in range(19):
        mixed = seed ^ (0xABCD1234 >> index)
        mask.append(((mixed & 0xFF) + (mixed >> 8)) & 0xFF)
    return bytes(value ^ mask[index % 19] for index, value in enumerate(body))


def build_command(pid: int, metadata: CommandMetadata, commands: CommandPairs, context: datetime) -> bytes:
    """Encode 1..255 ordered index/value pairs using the supplied local time.

    The eight-byte header stays clear. The metadata, command count/pairs and
    MAC-masked checksum are encoded together; plaintext is never a send fallback.
    """
    _unsigned(pid, 16)
    if not isinstance(metadata.mac, bytes) or len(metadata.mac) != 6:
        raise ValueError("FC25 requires a six-byte MAC")
    _unsigned(metadata.device_type, 8)
    _unsigned(metadata.config, 8)
    if not 1 <= len(commands) <= 255:
        raise ValueError("FC25 requires 1..255 command pairs")
    pairs = bytearray()
    for index, value in commands:
        _unsigned(index, 16)
        _unsigned(value, 16)
        pairs.extend(index.to_bytes(2, "big") + value.to_bytes(2, "big"))
    meta = bytes.fromhex("001012345678") + b"simon" + bytes(27) + metadata.mac + bytes((metadata.device_type, metadata.config))
    data = meta + bytes((len(commands),)) + pairs
    prefix = pid.to_bytes(2, "big") + bytes.fromhex("2010") + len(data).to_bytes(2, "big")
    header = prefix + bytes((sum(prefix) & 0xFF, 0x25))
    checksum = ((sum(header) + sum(data)) & 0xFFFF) ^ int.from_bytes(metadata.mac[-2:], "big")
    return header + _transform(data + checksum.to_bytes(2, "big"), context)


def validate_response(response: bytes, request: bytes, context: datetime) -> None:
    """Accept a checksummed empty ACK or the decoded complete command echo.

    Response protocol ID is 0x1020. An empty ACK carries no completion state.
    Echoes must preserve the submitted metadata and ordered pairs; decoding
    permits plaintext replies and the device's adjacent-minute time window.
    Malformed, mismatched and error responses fail without requesting a resend.
    """
    if len(response) < 10:
        raise PacketSizeError(10, len(response))
    if response[:2] != request[:2]:
        raise ResponsePidMismatchError(1)
    if response[2:4] != bytes.fromhex("1020") or response[6] != sum(response[:6]) & 0xFF:
        raise CommandResponseError("Invalid FC25 response header")
    if response[7] != 0x25:
        raise CommandResponseError(f"Unexpected FC25 response function: {response[7]:#04x}")
    length = int.from_bytes(response[4:6], "big")
    if len(response) != length + 10:
        raise PacketSizeError(length + 10, len(response))
    if length == 0:
        if int.from_bytes(response[8:], "big") != sum(response[:8]) & 0xFFFF:
            raise CommandResponseError("Invalid FC25 acknowledgement checksum")
        return
    if response[4:8] != request[4:8]:
        raise CommandResponseError("FC25 response does not echo the command header")
    expected = _transform(request[8:], context)
    body = response[8:]
    if body == expected:
        return
    for offset in (0, -1, 1):
        if _transform(body, context + timedelta(minutes=offset)) == expected:
            return
    raise CommandResponseError("FC25 response does not echo the submitted command")
