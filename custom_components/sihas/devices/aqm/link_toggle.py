"""AQM toggle-only link control: one existing rule's stored enable state.

R62 holds the enable bit of all ten rules, but only the R50-selected bank exposes
that rule's R51-R61 content, and a rule's enabled state is the pair of R61 bit15
(the packed time `enabled` bit31) and its R62 bit. A toggle is therefore one
serialized transaction owned by this module:

1. validate the rule index and target state;
2. write R50 = rule, then read the device again inside the same transaction;
3. require the fresh R50 to equal the rule before attributing R51-R61 to it;
4. reject enabling an empty bank (no bit set in R51-R61 other than the enable bit);
5. write R61 with only bit15 changed and R62 with only the rule bit changed, each
   only when it differs from the fresh readback;
6. read again and require R50, both enable bits, R51-R60, R61 bits0-14 and every
   other R62 bit to match; anything else is a failure, never success.

R50 is left on the toggled rule and is not restored: selection changes only which
bank the device exposes, never rule content. Another client can move R50 at any
time; a selector mismatch at any verification point aborts before a bank write.
After any issued I/O the coordinator refresh publishes the actual device state.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..controls import non_enable_bits_set
from . import link

if TYPE_CHECKING:
    from ..definition import CommandExecution, CommandPolicy, CommandValue
    from ..state import DeviceSnapshot

RULES = 10
SELECTOR, BANK_FIRST, TIME_HIGH, ENABLE_MASK = 50, 51, 61, 62
TIME_ENABLED = 0x8000  # R61 bit15 is bit31 of the packed R60/R61 time word.
_CONTENT = slice(BANK_FIRST, TIME_HIGH)  # R51-R60


class LinkToggleError(Exception):
    """The toggle could not be completed and verified; the device state is reported by the following refresh."""


def empty_bank(bank: Sequence[int]) -> bool:
    """Whether R51-R61 carry no rule content, ignoring only the paired enable bit."""
    if len(bank) != 11:
        raise ValueError("A link bank has exactly eleven words")
    return not non_enable_bits_set(bank, 10, TIME_ENABLED)


def enabled(selected: link.SelectedLink | None, rule: int) -> bool | None:
    """The rule's published R62 enable bit, the switch state; None without a valid mask."""
    rules = selected.enabled_rules if selected is not None else None
    return rules[link.selector_value(rule)] if rules is not None else None


def _fresh(registers: Sequence[int]) -> tuple[int, ...]:
    if len(registers) <= ENABLE_MASK or not all(type(word) is int and 0 <= word <= 0xFFFF for word in registers[:ENABLE_MASK + 1]):
        raise LinkToggleError("Link readback is incomplete")
    return tuple(registers)


def edited_words(registers: Sequence[int], rule: int, target: bool) -> tuple[int, int]:
    """(R61, R62) from a fresh read with only R61 bit15 and the rule's R62 bit set to `target`."""
    r61, r62 = registers[TIME_HIGH], registers[ENABLE_MASK]
    return (r61 | TIME_ENABLED if target else r61 & ~TIME_ENABLED), link.set_enabled(r62, rule, target)


def verify(selected: Sequence[int], final: Sequence[int], rule: int, target: bool) -> None:
    """Require exactly the requested enable state and unchanged content/unrelated bits."""
    rule_bit = 1 << rule
    if final[SELECTOR] != rule:
        raise LinkToggleError(f"Link selector moved to {final[SELECTOR]} during the toggle of rule {rule + 1}")
    if final[_CONTENT] != selected[_CONTENT]:
        raise LinkToggleError(f"Link rule {rule + 1} content changed during the toggle")
    if final[TIME_HIGH] & ~TIME_ENABLED != selected[TIME_HIGH] & ~TIME_ENABLED:
        raise LinkToggleError(f"Link rule {rule + 1} time bits changed during the toggle")
    if final[ENABLE_MASK] & ~rule_bit != selected[ENABLE_MASK] & ~rule_bit:
        raise LinkToggleError("Unrelated link enable bits changed during the toggle")
    if bool(final[TIME_HIGH] & TIME_ENABLED) is not target or bool(final[ENABLE_MASK] & rule_bit) is not target:
        raise LinkToggleError(f"Link rule {rule + 1} enable state did not reach {'on' if target else 'off'}")


async def toggle(rule: int, snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
    """Set one existing rule's paired enable state; see the module contract."""
    link.selector_value(rule)
    if type(value) is not bool:
        raise ValueError(f"Invalid link rule enable request: {value}")
    if execution.read is None or execution.refresh is None:
        raise ValueError("AQM link toggles require the fresh-read and refresh effects")
    try:
        await execution.write((SELECTOR, rule))
        selected = _fresh(await execution.read())
        if selected[SELECTOR] != rule:
            raise LinkToggleError(f"Link selector reads {selected[SELECTOR]} instead of rule {rule + 1}")
        if value and empty_bank(selected[BANK_FIRST:ENABLE_MASK]):
            raise ValueError(f"Link rule {rule + 1} is empty and cannot be enabled")
        r61, r62 = edited_words(selected, rule, value)
        intents = [(register, word) for register, word in ((TIME_HIGH, r61), (ENABLE_MASK, r62)) if word != selected[register]]
        for intent in intents:
            await execution.write(intent)
        verify(selected, _fresh(await execution.read()) if intents else selected, rule, value)
    except Exception:
        await execution.refresh()
        raise
    await execution.refresh()


def policy(rule: int) -> CommandPolicy:
    link.selector_value(rule)

    async def execute(snapshot: DeviceSnapshot, value: CommandValue, execution: CommandExecution) -> None:
        await toggle(rule, snapshot, value, execution)
    return execute


def commands() -> dict[str, CommandPolicy]:
    """`link_rule_0` .. `link_rule_9` toggle policies."""
    return {f"link_rule_{rule}": policy(rule) for rule in range(RULES)}
