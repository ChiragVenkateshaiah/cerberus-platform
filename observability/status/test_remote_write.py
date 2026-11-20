"""Tests for remote_write.py with a test-only protobuf and snappy decoder.

No AWS and no network. Run: pytest observability/status
"""

import math
import os
import struct

import pytest
import remote_write


def read_varint(buf, i):
    shift = value = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7


def fields(buf):
    """Yield (field number, wire type, value) of one protobuf message."""
    i = 0
    while i < len(buf):
        tag, i = read_varint(buf, i)
        num, wire = tag >> 3, tag & 7
        if wire == 0:
            value, i = read_varint(buf, i)
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        elif wire == 2:
            n, i = read_varint(buf, i)
            value, i = buf[i : i + n], i + n
        else:
            raise AssertionError(f"unexpected wire type {wire}")
        yield num, wire, value


def decode(buf):
    """WriteRequest bytes -> [(ordered [(name, value)] labels, [(value, ts)])]."""
    out = []
    for num, wire, ts_bytes in fields(buf):
        assert (num, wire) == (1, 2)
        labels, samples = [], []
        for n, w, v in fields(ts_bytes):
            if n == 1:
                lab = {k: val.decode() for k, _, val in fields(v)}
                labels.append((lab[1], lab[2]))
            else:
                assert (n, w) == (2, 2)
                f = {k: (ww, val) for k, ww, val in fields(v)}
                assert f[1][0] == 1 and f[2][0] == 0
                value = struct.unpack("<d", f[1][1])[0]
                ts = f[2][1]
                if ts >= 1 << 63:
                    ts -= 1 << 64
                samples.append((value, ts))
        out.append((labels, samples))
    return out


def unsnappy(buf):
    """Decode snappy raw format that holds literal elements only."""
    length, i = read_varint(buf, 0)
    out = bytearray()
    while i < len(buf):
        tag = buf[i]
        i += 1
        assert tag & 3 == 0, "not a literal element"
        n = tag >> 2
        if n >= 60:
            size = n - 59
            n = int.from_bytes(buf[i : i + size], "little")
            i += size
        n += 1
        out += buf[i : i + n]
        i += n
    assert i == len(buf)
    assert len(out) == length
    return bytes(out)


SERIES = [
    ("cerberus_run_step_failed", {"step": "RunDbt"}, 1.0),
    ("cerberus_run_status", {}, 0.0),
    ("cerberus_run_info", {"execution": "e1", "aaa": "z"}, 1.0),
    ("cerberus_dq_errors", {}, float("nan")),
    ("cerberus_run_started_timestamp_seconds", {}, 1791450813.494),
]


def test_encode_round_trip():
    ts = 1795168800000
    decoded = decode(remote_write.encode(SERIES, ts))
    assert len(decoded) == len(SERIES)
    got = {tuple(labels): samples for labels, samples in decoded}
    for name, labels, value in SERIES:
        key = tuple(sorted({"__name__": name, **labels}.items()))
        ((v, t),) = got[key]
        assert t == ts
        assert (math.isnan(v) and math.isnan(value)) or v == value


def test_labels_sorted_with_name_in_place():
    decoded = decode(remote_write.encode(SERIES, 1))
    for labels, _ in decoded:
        names = [k for k, _ in labels]
        assert names == sorted(names)
    # "__name__" sorts before "aaa" and "execution" ("_" is 0x5f, "a" is 0x61)
    info = next(lab for lab, _ in decoded if ("aaa", "z") in lab)
    assert [k for k, _ in info] == ["__name__", "aaa", "execution"]


def test_one_timestamp_for_all_samples():
    decoded = decode(remote_write.encode(SERIES, 1795168800123))
    assert {t for _, samples in decoded for _, t in samples} == {1795168800123}


def test_nan_is_not_the_stale_marker():
    body = remote_write.encode([("m", {}, float("nan"))], 1)
    ((_, ((v, _),)),) = decode(body)
    assert math.isnan(v)
    assert struct.pack("<d", v) != struct.pack("<Q", 0x7FF0000000000002)


def test_encode_is_deterministic_in_any_input_order():
    assert remote_write.encode(SERIES, 5) == remote_write.encode(SERIES[::-1], 5)


def test_known_bytes():
    # one series {__name__="m"}, value 1.0, ts 1; checked by hand against the proto
    body = remote_write.encode([("m", {}, 1.0)], 1)
    label = b"\x0a\x08__name__\x12\x01m"
    sample = b"\x09" + struct.pack("<d", 1.0) + b"\x10\x01"
    ts = b"\x0a" + bytes([len(label)]) + label + b"\x12" + bytes([len(sample)]) + sample
    assert body == b"\x0a" + bytes([len(ts)]) + ts


def test_headers():
    assert remote_write.HEADERS == {
        "Content-Encoding": "snappy",
        "Content-Type": "application/x-protobuf",
        "X-Prometheus-Remote-Write-Version": "0.1.0",
        "User-Agent": "cerberus-status-publisher",
    }


@pytest.mark.parametrize("n", [0, 1, 59, 60, 61, 255, 256, 257, 65535, 65536, 65537])
def test_snappy_round_trip(n):
    data = os.urandom(n)
    assert unsnappy(remote_write.snappy_block(data)) == data


@pytest.mark.parametrize(
    "n, tag, length_bytes",
    [(1, 0x00, 0), (60, 0xEC, 0), (61, 0xF0, 1), (256, 0xF0, 1), (257, 0xF4, 2),
     (65536, 0xF4, 2), (65537, 0xF8, 3), (1 << 24, 0xF8, 3), ((1 << 24) + 1, 0xFC, 4)],
)  # fmt: skip
def test_literal_length_forms(n, tag, length_bytes):
    chunk = bytes(n)
    element = remote_write._literal(chunk)
    assert element[0] == tag
    assert len(element) == 1 + length_bytes + n
    if length_bytes:
        assert int.from_bytes(element[1 : 1 + length_bytes], "little") == n - 1


def test_snappy_preamble_is_uncompressed_length():
    out = remote_write.snappy_block(b"x" * 300)
    length, _ = read_varint(out, 0)
    assert length == 300
    assert out[:2] == b"\xac\x02"


def test_70kb_payload_spans_several_literals():
    data = os.urandom(70 * 1024)
    out = remote_write.snappy_block(data)
    _, i = read_varint(out, 0)
    elements = 0
    while i < len(out):
        tag = out[i]
        assert tag & 3 == 0
        n = tag >> 2
        size = n - 59 if n >= 60 else 0
        n = int.from_bytes(out[i + 1 : i + 1 + size], "little") if size else n
        i += 1 + size + n + 1
        elements += 1
    assert i == len(out)
    assert elements == 3
    assert unsnappy(out) == data


def test_empty_payload_is_only_the_preamble():
    assert remote_write.snappy_block(b"") == b"\x00"


GOLDEN = "0a1c0a0d0a085f5f6e616d655f5f12016d120b09000000000000f03f1001"


def test_golden_encode():
    # Hand-derived from the prompb wire format, not via the test decoder.
    assert remote_write.encode([("m", {}, 1.0)], 1).hex() == GOLDEN


def test_golden_snappy():
    raw = bytes.fromhex(GOLDEN)
    assert len(raw) == 30
    assert remote_write.snappy_block(raw) == bytes.fromhex("1e74") + raw


def test_golden_literal_and_varint_forms():
    # Snappy: length-1 up to 59 fits in the tag; 61 bytes is the first 1-byte length form.
    assert remote_write._literal(b"x" * 60)[:2] == b"\xecx"
    assert remote_write._literal(b"x" * 61)[:3] == b"\xf0\x3cx"
    assert remote_write._literal(b"x" * 257)[:3] == b"\xf4\x00\x01"
    assert remote_write._varint(-1) == b"\xff" * 9 + b"\x01"


def test_nan_bits_are_the_canonical_quiet_nan():
    body = remote_write.encode([("m", {}, float("nan"))], 1)
    ((_, ((v, _),)),) = decode(body)
    assert struct.pack("<d", v) == struct.pack("<Q", 0x7FF8000000000000)
