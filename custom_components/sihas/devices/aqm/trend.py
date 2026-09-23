"""Offline AQM single-day raw sample blocks, independent of packet and sensor semantics."""
from collections.abc import Sequence


def _values(values: Sequence[int], count: int, maximum: int) -> tuple[int, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str) or len(values) != count:
        raise ValueError(f"Expected exactly {count} integers")
    result = tuple(values)
    if any(type(value) is not int or not 0 <= value <= maximum for value in result):
        raise ValueError(f"Values must be integers in 0..{maximum}")
    return result


def decode_samples(block: Sequence[int]) -> tuple[int, ...]:
    """Decode exactly 576 bytes as 288 unsigned big-endian words without scaling."""
    raw = _values(block, 576, 255)
    return tuple((raw[index] << 8) | raw[index + 1] for index in range(0, 576, 2))


def pack_samples(samples: Sequence[int]) -> bytes:
    """Pack exactly 288 raw words; no missing-value or sensor interpretation."""
    words = _values(samples, 288, 65535)
    return b"".join(word.to_bytes(2, "big") for word in words)


def sample_clock(index: int) -> tuple[int, int]:
    """Return (hour, minute) within one day, without a date or weekday selector."""
    if type(index) is not int or not 0 <= index < 288:
        raise ValueError("Sample index must be an integer in 0..287")
    return index // 12, (index % 12) * 5
