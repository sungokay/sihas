"""Cross-family control policy primitives; no HA, I/O or register ownership.

Families that expose an equivalent user-facing control pattern share these rules
even when their wire layouts differ. Each family still owns its register
addresses, bit masks, encodings, options and evidence gate; these helpers only
apply the common policy to the raw words and bounds a family supplies.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

# Integer-Celsius SiHAS public policy for a lower/upper limit pair; each endpoint is further bounded by its counterpart.
LIMIT_MINIMUM, LIMIT_MAXIMUM = 0, 100
# Stored weekday masks use Sunday as bit0 and Saturday as bit6.
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


def _word(value: int | None) -> bool:
    return type(value) is int and 0 <= value <= 65535


def exact_tenths(value: int | float | Decimal) -> int:
    """Normalize numeric decimal input without truncation; each encoder owns its own bounds."""
    if type(value) not in (int, float, Decimal):
        raise ValueError("Value requires a number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Value must be finite")
    numerator, denominator = number.as_integer_ratio()
    tenths, remainder = divmod(numerator * 10, denominator)
    if remainder:
        raise ValueError("Value requires exact tenths")
    return tenths


@dataclass(frozen=True)
class NumberRange:
    """Home Assistant public capability range in exact tenths of the presented unit.

    This is SiHAS user-facing policy. It is neither the device's storable wire
    range nor the small set of points used for physical write qualification.
    """

    low: int
    high: int
    step: int

    @property
    def minimum(self) -> Decimal:
        return Decimal(self.low) / 10

    @property
    def maximum(self) -> Decimal:
        return Decimal(self.high) / 10

    @property
    def increment(self) -> Decimal:
        return Decimal(self.step) / 10

    def tenths(self, value: int | float | Decimal) -> int:
        """Exact on-step tenths inside the range, otherwise ValueError."""
        tenths = exact_tenths(value)
        if not self.low <= tenths <= self.high or (tenths - self.low) % self.step:
            raise ValueError(f"Value {value} is outside {self.minimum}..{self.maximum} step {self.increment}")
        return tenths


def lower_limit_range(upper: int | None) -> NumberRange | None:
    """Lower endpoint range from the counterpart upper readback: policy minimum .. upper - 1 C.

    A missing counterpart or an empty range yields None: no range is fabricated and no write is allowed.
    """
    if upper is None:
        return None
    high = min(upper - 1, LIMIT_MAXIMUM - 1)
    return NumberRange(LIMIT_MINIMUM * 10, high * 10, 10) if high >= LIMIT_MINIMUM else None


def upper_limit_range(lower: int | None) -> NumberRange | None:
    """Upper endpoint range from the counterpart lower readback: lower + 1 .. policy maximum C."""
    if lower is None:
        return None
    low = max(lower + 1, LIMIT_MINIMUM + 1)
    return NumberRange(low * 10, LIMIT_MAXIMUM * 10, 10) if low <= LIMIT_MAXIMUM else None


def weekday_names(mask: int) -> tuple[str, ...]:
    """Selected weekdays of a decoded stored mask, in Sunday-first bit order."""
    if type(mask) is not int or not 0 <= mask <= 127:
        raise ValueError(f"Invalid weekdays: {mask}")
    return tuple(name for bit, name in enumerate(WEEKDAYS) if mask >> bit & 1)


@dataclass(frozen=True)
class StoredToggle:
    """One safe enable bit inside manufacturer-owned stored configuration.

    Only the enable bit is controlled. Every other bit of the enable word and of
    the paired storage words is preserved; decoding the rest is optional
    descriptive metadata and never a prerequisite for this toggle. `populated`
    is supplied by the family/feature owner: whether this valid raw entry is a
    stored entry that exists (including a valid default state) rather than empty.
    """

    register: int
    word: int
    mask: int
    populated: bool

    @property
    def enabled(self) -> bool:
        return bool(self.word & self.mask)

    @property
    def offered(self) -> bool:
        """Whether this entry is presented as a toggle.

        A populated entry is a normal enable switch. An entry its owner reports as empty is not
        offered, except one whose enable bit is already set, which stays offered only so it can be disabled.
        """
        return self.populated or self.enabled

    def intent(self, enabled: bool) -> tuple[int, int]:
        """One-register read-modify-write of the transaction-start word.

        An entry that is not offered is rejected, and enabling empty storage is rejected:
        toggling never creates a new stored entry.
        """
        if type(enabled) is not bool:
            raise ValueError(f"Invalid enable request: {enabled}")
        if not self.offered:
            raise ValueError("Empty stored configuration is not a controllable entry")
        if enabled and not self.populated:
            raise ValueError("Empty stored configuration cannot be enabled")
        return self.register, self.word | self.mask if enabled else self.word & ~self.mask


def toggle_offered(toggle: StoredToggle | None) -> bool:
    """Presentation rule shared by every stored-entry toggle: valid raw storage that is offered."""
    return toggle is not None and toggle.offered


def non_enable_bits_set(words: Sequence[int], enable_index: int, mask: int) -> bool:
    """Whether any bit other than the enable bit is set in the entry's words.

    Pure bit arithmetic; a family decides whether this means its entry exists.
    """
    return any(word & ~mask if index == enable_index else word for index, word in enumerate(words))


def stored_toggle(register: int, words: Sequence[int | None], enable_index: int, mask: int, *,
                  populated: Callable[[Sequence[int]], bool]) -> StoredToggle | None:
    """Toggle over one stored entry's complete raw words, or None when any word is missing/invalid.

    `words[enable_index]` is the word written back at `register`. The family-owned
    `populated` rule receives the validated words; this layer assigns no existence meaning.
    """
    if not all(_word(word) for word in words):
        return None
    return StoredToggle(register, words[enable_index], mask, populated(words))
