"""Minimal .dbf reader (no arcpy, no third-party packages).

Used where only attribute values are needed. It does not depend on the shapefile name (ArcPy
cannot resolve names that contain a dot) and is fast for large tables.
"""

import os
import struct


RECORD = "@record"


def read_dbf_columns(dbf_path, wanted, record_index=False):
    """Read selected columns of a .dbf file.

    Args:
        dbf_path: path of the .dbf file
        wanted: field names (case-insensitive)
        record_index: also return the position of every record under the key RECORD. In a
            shapefile this position is the object ID (FID) arcpy uses.
    Returns:
        (dict field name -> list of values, number of records). Numeric (N/F) fields become
        float or None, other fields stripped strings. Deleted records are skipped.
    Raises:
        KeyError if a requested field does not exist.
    """
    with open(dbf_path, "rb") as fh:
        data = fh.read()

    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = []
    pos = 32
    offset = 1  # first byte of every record is the deletion flag
    while pos < len(data) and data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode("ascii", "replace")
        ftype = chr(data[pos + 11])
        length = data[pos + 16]
        fields.append((name, ftype, offset, length))
        offset += length
        pos += 32

    by_lower = {f[0].lower(): f for f in fields}
    selected = []
    for name in wanted:
        if name.lower() not in by_lower:
            raise KeyError(f"Field '{name}' not found in {os.path.basename(dbf_path)}")
        selected.append(by_lower[name.lower()])

    result = {name: [] for name in wanted}
    if record_index:
        result[RECORD] = []
    count = 0
    for i in range(n_records):
        start = header_len + i * record_len
        record = data[start:start + record_len]
        if not record or record[0:1] == b"*":
            continue
        count += 1
        if record_index:
            result[RECORD].append(i)
        for name, (_, ftype, off, length) in zip(wanted, selected):
            raw = record[off:off + length].decode("utf-8", "replace").strip()
            if ftype in ("N", "F"):
                try:
                    value = float(raw) if raw else None
                except ValueError:
                    value = None
            else:
                value = raw
            result[name].append(value)
    return result, count


def to_number(value):
    """Float of a number or a numeric text (PRA fields are stored as text); None if impossible."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
