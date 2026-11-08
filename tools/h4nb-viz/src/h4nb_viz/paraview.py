"""VTK PolyData (.vtp) writer for one snapshot (FR-016).

Appended raw binary, little-endian, UInt64 block headers. numpy and stdlib only.
"""
from __future__ import annotations

import struct
from xml.sax.saxutils import quoteattr

import numpy as np

from h4nb_viz.orbits import e_inc


def write_vtp(path, positions, velocities, masses, ids, mu=1.0):
    """Write particles as one VTK PolyData file with one vertex per particle.

    positions, velocities: shape (k, 3). masses: shape (k,). ids: shape (k,).
    Particle 0 is the central body. mu is G times its mass (used for e and inc).
    Points are float32. The ids are int64.
    """
    pos = np.asarray(positions, dtype="<f4").reshape(-1, 3)
    vel = np.asarray(velocities, dtype="<f4").reshape(-1, 3)
    mass = np.asarray(masses, dtype="<f4").reshape(-1)
    ident = np.asarray(ids, dtype="<i8").reshape(-1)
    n = len(pos)
    if not (len(vel) == len(mass) == len(ident) == n):
        raise ValueError("positions, velocities, masses and ids must have the same length")

    # Derived point data (FR-016). r is measured from the central body.
    speed = np.linalg.norm(vel, axis=1).astype("<f4") if n else np.zeros(0, "<f4")
    r = np.linalg.norm(pos - pos[:1], axis=1).astype("<f4") if n else np.zeros(0, "<f4")
    if n:
        e, inc = (a.astype("<f4") for a in e_inc(pos, vel, mu))
    else:
        e = inc = np.zeros(0, "<f4")

    # Vertex cells: cell i holds point i.
    conn = np.arange(n, dtype="<i8")
    offs = np.arange(1, n + 1, dtype="<i8")

    # (name, type, components, data) in the order of the file.
    arrays = [
        ("points", "Float32", 3, pos),
        ("connectivity", "Int64", 1, conn),
        ("offsets", "Int64", 1, offs),
        ("id", "Int64", 1, ident),
        ("m", "Float32", 1, mass),
        ("v", "Float32", 3, vel),
        ("speed", "Float32", 1, speed),
        ("r", "Float32", 1, r),
        ("e", "Float32", 1, e),
        ("inc", "Float32", 1, inc),
    ]

    # Each block is a UInt64 byte count and the data. The offset is the block start.
    blobs, offset_of, pos_now = [], {}, 0
    for name, _, _, data in arrays:
        raw = data.tobytes()
        offset_of[name] = pos_now
        blobs.append(struct.pack("<Q", len(raw)) + raw)
        pos_now += 8 + len(raw)

    def decl(name, dtype, comps=1):
        c = f' NumberOfComponents="{comps}"' if comps != 1 else ""
        return f'<DataArray type="{dtype}" Name={quoteattr(name)}{c} format="appended" offset="{offset_of[name]}"/>'

    head = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n'
        "  <PolyData>\n"
        f'    <Piece NumberOfPoints="{n}" NumberOfVerts="{n}" NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="0">\n'
        "      <Points>\n"
        f"        {decl('points', 'Float32', 3)}\n"
        "      </Points>\n"
        "      <Verts>\n"
        f"        {decl('connectivity', 'Int64')}\n"
        f"        {decl('offsets', 'Int64')}\n"
        "      </Verts>\n"
        "      <PointData>\n"
        f"        {decl('id', 'Int64')}\n"
        f"        {decl('m', 'Float32')}\n"
        f"        {decl('v', 'Float32', 3)}\n"
        f"        {decl('speed', 'Float32')}\n"
        f"        {decl('r', 'Float32')}\n"
        f"        {decl('e', 'Float32')}\n"
        f"        {decl('inc', 'Float32')}\n"
        "      </PointData>\n"
        "    </Piece>\n"
        "  </PolyData>\n"
        '  <AppendedData encoding="raw">\n'
        "_"
    ).encode()
    tail = b"\n</AppendedData>\n</VTKFile>\n"

    with open(path, "wb") as f:
        f.write(head + b"".join(blobs) + tail)
