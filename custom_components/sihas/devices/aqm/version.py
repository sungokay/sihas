"""Offline AQM numeric version representation, unrelated to installed text or upgrade policy."""
from dataclasses import dataclass


def _integer(value: int, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Version value must be an integer in 0..{maximum}")
    return value


def pack_version(major: int, minor: int) -> int:
    """Pack explicit components into uint16, preserving the base-100 minor boundary."""
    return _integer(_integer(major, 655) * 100 + _integer(minor, 99), 65535)


@dataclass(frozen=True)
class Version:
    """Validated numeric components; neither a release observation nor feature qualification."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        pack_version(self.major, self.minor)

    @property
    def packed(self) -> int:
        return pack_version(self.major, self.minor)


def decode_version(packed: int) -> Version:
    return Version(*divmod(_integer(packed, 65535), 100))


def same_major_minor_at_least(current: Version, required: Version) -> bool:
    """Compare explicit components only; a different major never satisfies this predicate."""
    if not isinstance(current, Version) or not isinstance(required, Version):
        raise ValueError("Comparison requires validated Version components")
    return current.major == required.major and current.minor >= required.minor
