"""Tests for the VTK PolyData (.vtp) writer."""
import struct
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from h4nb_viz.orbits import e_inc
from h4nb_viz.paraview import write_vtp

# Expected (name, type, components) of each array, in file order (FR-016).
EXPECTED = [
    ("points", "Float32", 3),
    ("id", "Int64", 1),
    ("m", "Float32", 1),
    ("v", "Float32", 3),
    ("speed", "Float32", 1),
    ("r", "Float32", 1),
    ("e", "Float32", 1),
    ("inc", "Float32", 1),
]


def _split(path):
    """Return the XML tree and the appended binary payload of a .vtp file."""
    raw = open(path, "rb").read()
    start = raw.index(b"<AppendedData")
    marker = raw.index(b"_", start) + 1
    end = raw.rindex(b"\n</AppendedData>")
    # The XML part ends before AppendedData. Close the root so ET can parse it.
    root = ET.fromstring(raw[:start] + b"</VTKFile>")
    return root, raw[marker:end]


def _arrays(root):
    """Return the DataArray elements by name."""
    found = {}
    for el in root.iter("DataArray"):
        found[el.get("Name")] = el
    return found


def _check_file(path, n):
    root, payload = _split(path)
    assert root.get("type") == "PolyData"
    assert root.get("byte_order") == "LittleEndian"
    assert root.get("header_type") == "UInt64"

    piece = root.find("PolyData/Piece")
    assert piece.get("NumberOfPoints") == str(n)
    assert piece.get("NumberOfVerts") == str(n)

    arrays = _arrays(root)
    for name, dtype, comps in EXPECTED:
        el = arrays[name]
        assert el.get("type") == dtype
        assert el.get("NumberOfComponents", "1") == str(comps)
        assert el.get("format") == "appended"

    # Each block is a UInt64 byte count followed by the data.
    # Blocks follow each other, so each offset equals the end of the one before.
    blocks = sorted(arrays.values(), key=lambda el: int(el.get("offset")))
    expected_pos = 0
    for el in blocks:
        off = int(el.get("offset"))
        assert off == expected_pos
        (nbytes,) = struct.unpack("<Q", payload[off:off + 8])
        expected_pos = off + 8 + nbytes
    assert expected_pos == len(payload)
    return root, payload, arrays


def _block(payload, arrays, name, dtype):
    off = int(arrays[name].get("offset"))
    (nbytes,) = struct.unpack("<Q", payload[off:off + 8])
    return np.frombuffer(payload[off + 8:off + 8 + nbytes], dtype=dtype)


def test_zero_particles(tmp_path):
    path = tmp_path / "empty.vtp"
    write_vtp(str(path), np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0), np.zeros(0, dtype=np.int64))
    root, payload, arrays = _check_file(str(path), 0)
    # Every array is empty, so every byte count is zero.
    for el in arrays.values():
        (nbytes,) = struct.unpack("<Q", payload[int(el.get("offset")):int(el.get("offset")) + 8])
        assert nbytes == 0


def test_several_particles(tmp_path):
    n = 5
    rng = np.random.default_rng(1)
    pos = rng.standard_normal((n, 3))
    vel = rng.standard_normal((n, 3))
    mass = rng.random(n)
    ids = np.arange(100, 100 + n, dtype=np.int64)
    path = tmp_path / "some.vtp"
    write_vtp(str(path), pos, vel, mass, ids)

    root, payload, arrays = _check_file(str(path), n)

    np.testing.assert_array_equal(_block(payload, arrays, "points", "<f4").reshape(n, 3), pos.astype(np.float32))
    np.testing.assert_array_equal(_block(payload, arrays, "v", "<f4").reshape(n, 3), vel.astype(np.float32))
    np.testing.assert_array_equal(_block(payload, arrays, "m", "<f4"), mass.astype(np.float32))
    np.testing.assert_array_equal(_block(payload, arrays, "id", "<i8"), ids)
    np.testing.assert_array_equal(_block(payload, arrays, "connectivity", "<i8"), np.arange(n))
    np.testing.assert_array_equal(_block(payload, arrays, "offsets", "<i8"), np.arange(1, n + 1))


def test_derived_fields_match_norms_and_orbits(tmp_path):
    n = 6
    rng = np.random.default_rng(2)
    pos = rng.standard_normal((n, 3))
    vel = rng.standard_normal((n, 3))
    path = tmp_path / "derived.vtp"
    write_vtp(str(path), pos, vel, np.ones(n), np.arange(n, dtype=np.int64), mu=2.0)

    _, payload, arrays = _check_file(str(path), n)

    speed = _block(payload, arrays, "speed", "<f4")
    r = _block(payload, arrays, "r", "<f4")
    e = _block(payload, arrays, "e", "<f4")
    inc = _block(payload, arrays, "inc", "<f4")

    # The file stores float32 inputs, so the references use the same values.
    pos32, vel32 = pos.astype(np.float32), vel.astype(np.float32)

    # speed is |v|, r is the distance from the central body (particle 0).
    np.testing.assert_allclose(speed, np.linalg.norm(vel32, axis=1), rtol=1e-6)
    np.testing.assert_allclose(r, np.linalg.norm(pos32 - pos32[0], axis=1), rtol=1e-6)

    # e and inc come from orbits.e_inc with the same mu. The central body has NaN.
    e_ref, inc_ref = e_inc(pos32.astype(np.float64), vel32.astype(np.float64), mu=2.0)
    np.testing.assert_allclose(e, e_ref.astype(np.float32), rtol=1e-6, equal_nan=True)
    np.testing.assert_allclose(inc, inc_ref.astype(np.float32), rtol=1e-6, equal_nan=True)
    assert np.isnan(e[0]) and np.isnan(inc[0])
    assert r[0] == 0.0


def test_mismatched_lengths_raise(tmp_path):
    with pytest.raises(ValueError):
        write_vtp(str(tmp_path / "bad.vtp"), np.zeros((3, 3)), np.zeros((2, 3)), np.zeros(3), np.zeros(3, dtype=np.int64))
