"""HA-independent SiHAS wire-protocol and network mechanics.

Packet framing, protocol-level constants, textual identification parsing and the
synchronous register/discovery transports live here. Home Assistant identity,
config schema, entity/presentation policy and executor scheduling stay outside
this boundary; HA/runtime modules depend on it, never the reverse.
"""
