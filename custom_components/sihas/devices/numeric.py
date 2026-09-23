"""Existing numeric conversions used by device fields; no HA dependencies."""

def register_put_u32(b1: int, b2: int) -> int:
    return b1 | (b2 << 16)


def reg_to_int16(value: int) -> int:
    """Reinterpret a 16-bit unsigned register value as a signed int16.

    Modbus registers are unsigned; some device fields encode signed values
    using two's-complement int16.  This helper converts without mutating the
    shared register array.

    Examples:
        reg_to_int16(0x0000) ->     0
        reg_to_int16(0x012C) ->   300
        reg_to_int16(0xFFFE) ->    -2
        reg_to_int16(0xFFF6) ->   -10
    """
    return value if value < 0x8000 else value - 0x10000


def normalize(r1: tuple[int, int], r2: tuple[int, int], v: int) -> int:
    """
    Normalize value "v" from ragne "r1" to "r2"

    For example, brightness ranged between 0 to 255 in HA,
    but in sihas, it sould be 1 to 100. 0 does mean "off" in sihas.

        normalize((0, 255), (1, 100), 168) #
    """
    # Calculate the percentage of v in the source range
    percentage = (v - r1[0]) / (r1[1] - r1[0])

    # Map the percentage to the target range
    normalized_value = r2[0] + percentage * (r2[1] - r2[0])

    # Round the result to the nearest integer
    return round(normalized_value)
