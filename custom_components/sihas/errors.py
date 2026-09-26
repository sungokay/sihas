class PacketSizeError(Exception):
    """Not excpeted length"""

    def __init__(self, expect: int, actual: int) -> None:
        self._expect = expect
        self._actual = actual

    def __str__(self) -> str:
        return f"packet size does not match: expect {self._expect}, but actual {self._actual}, may modbus not enabled"


class ResponsePidMismatchError(Exception):
    """No command acknowledgement echoed its request PID within the bounded PID attempts."""

    def __init__(self, attempts: int) -> None:
        self._attempts = attempts

    def __str__(self) -> str:
        return f"no acknowledgement matched the request PID in {self._attempts} attempts"


class ModbusNotEnabledError(Exception):
    """Modbus not enabled"""

    def __init__(self, device=None) -> None:
        self._device = device

    def __str__(self) -> str:
        detail = f": {self._device}" if self._device else ""
        return f"modbus does not enabled check in the app about device" + detail
