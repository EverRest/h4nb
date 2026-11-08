"""Parsers for the run files of h4nb_run (specs/001-hermite-nbody-lib/contracts/file-formats.md).

Source: the five functions of tools/h4nb-metrics/src/h4nb_metrics/readers.py at commit 7d0d42c
(specs/002-run-metrics). Specs/002 is not on main yet, so this copy is kept to these five
functions and their constants. Do not rename them without a notice to the specs/002 session
(plan.md DD6). The functions only parse text or bytes. They do not read files.
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

SNAP_MAGIC = b"H4NBSNAP"
SNAP_HEADER = struct.Struct("<8sIIQd")  # magic, version, reserved, n, time: 32 bytes


def parse_config_used(text: str) -> Dict[str, str]:
    """Parse `key=value  # source` lines. A key without a value is written as `# key=` and is skipped."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def parse_run_info(text: str) -> Dict[str, str]:
    """Parse `key: value` lines of run_info.txt."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key and " " not in key:
            out[key] = value.strip()
    return out


def parse_header(line: str) -> List[str]:
    """Column names of a `# a b c  (comment)` header line. Text from the first `(` is a comment."""
    names = []
    for tok in line.lstrip("#").split():
        if tok.startswith("("):
            break
        names.append(tok)
    return names


def parse_row(line: str, columns: List[str]) -> Optional[Dict[str, float]]:
    """Return one data line as a dict. Return None for a line with too few fields or a field that is not a number."""
    fields = line.split()
    if len(fields) < len(columns):
        return None
    try:
        return {c: float(f) for c, f in zip(columns, fields)}
    except ValueError:
        return None


def snapshot_header(data: bytes) -> Optional[Tuple[int, float]]:
    """Return (n, time) from the first 32 bytes of a snapshot. Return None when it is not a v1 snapshot."""
    if len(data) < SNAP_HEADER.size:
        return None
    magic, version, _, n, time = SNAP_HEADER.unpack(data[: SNAP_HEADER.size])
    if magic != SNAP_MAGIC or version != 1:
        return None
    return int(n), float(time)
