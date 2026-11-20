"""Prometheus remote-write request encoding, stdlib only, no network.

The protobuf is written by hand. Field numbers come from prometheus
prompb/types.proto and remote.proto and are proven against a real Prometheus
receiver in PR C (10.2c):
  WriteRequest.timeseries = 1
  TimeSeries.labels = 1, TimeSeries.samples = 2
  Label.name = 1, Label.value = 2
  Sample.value = 1 (double, fixed64), Sample.timestamp = 2 (int64, varint)
The body is snappy raw (block) format with literal elements only.
"""

import struct

HEADERS = {
    "Content-Encoding": "snappy",
    "Content-Type": "application/x-protobuf",
    "X-Prometheus-Remote-Write-Version": "0.1.0",
    "User-Agent": "cerberus-status-publisher",
}

# Longest literal element snappy_block writes. A longer payload spans several.
LITERAL_MAX = 32768


def _varint(n):
    if n < 0:  # int64 two's complement, 10 bytes
        n += 1 << 64
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _field(number, payload):
    """Length-delimited field (wire type 2)."""
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _label(name, value):
    return _field(1, name.encode()) + _field(2, value.encode())


def _timeseries(name, labels, value, ts_ms):
    pairs = sorted({"__name__": name, **labels}.items())
    body = b"".join(_field(1, _label(k, v)) for k, v in pairs)
    sample = b"\x09" + struct.pack("<d", value) + b"\x10" + _varint(ts_ms)
    return body + _field(2, sample)


def encode(series, ts_ms):
    """Series `(name, labels, value)` -> WriteRequest bytes.

    Labels are sorted by name, `__name__` included. Every sample gets `ts_ms`.
    Series are ordered by label set so the output is the same on every run.
    """
    ordered = sorted(series, key=lambda s: (s[0], sorted(s[1].items())))
    return b"".join(_field(1, _timeseries(n, lab, v, ts_ms)) for n, lab, v in ordered)


def _literal(chunk):
    """One snappy literal element: tag, optional length bytes, the bytes."""
    n = len(chunk) - 1
    if n < 60:
        return bytes([n << 2]) + chunk
    size = (n.bit_length() + 7) // 8  # 1 to 4 length bytes
    return bytes([(59 + size) << 2]) + n.to_bytes(size, "little") + chunk


def snappy_block(data):
    """Valid snappy raw format: length preamble, then literal elements only."""
    out = bytearray(_varint(len(data)))
    for i in range(0, len(data), LITERAL_MAX):
        out += _literal(data[i : i + LITERAL_MAX])
    return bytes(out)
