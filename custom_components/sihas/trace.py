"""Optional single-exchange evidence, handed off only after the producer finishes."""
from dataclasses import dataclass
from datetime import datetime, UTC
from time import monotonic


@dataclass(frozen=True)
class ExchangeEvent:
    attempt: int
    event: str
    timestamp: str
    elapsed_seconds: float
    payload: bytes | None = None
    error: str | None = None


class ExchangeTrace:
    """Request-local collector, never shared between exchanges or retained by I/O.

    One synchronous producer owns this object until finish(). The awaiting owner
    must drain that producer before reading freeze(), including on cancellation.
    Records are immutable; no callbacks, semantic processing or export occur here.
    """

    def __init__(self) -> None:
        self._started = monotonic()
        self._events: list[ExchangeEvent] = []
        self._finished = False

    def record(self, attempt: int, event: str, *, payload: bytes | None = None, error: str | None = None) -> None:
        if self._finished:
            raise RuntimeError("Exchange trace is already finished")
        self._events.append(ExchangeEvent(attempt, event, datetime.now(UTC).isoformat(), monotonic() - self._started, payload, error))

    def finish(self, attempt: int, outcome: str) -> None:
        self.record(attempt, "exchange_" + outcome)
        self._finished = True

    def freeze(self) -> tuple[ExchangeEvent, ...]:
        if not self._finished:
            raise RuntimeError("Exchange producer has not finished")
        return tuple(self._events)
