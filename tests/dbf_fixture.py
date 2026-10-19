"""Helpers for tests: write small .dbf files and ALARM-like scenario folders."""

import struct
from pathlib import Path


def write_dbf(path, fields, rows, deleted=()):
    """Write a dBase III file.

    fields: [(name, type, length, decimals)] with type 'C' or 'N'
    rows:   list of tuples (None is written as blanks)
    deleted: indices of rows to mark as deleted
    """
    record_len = 1 + sum(f[2] for f in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray()
    out += struct.pack("<BBBBIHH20x", 3, 126, 1, 1, len(rows), header_len, record_len)
    for name, ftype, length, decimals in fields:
        out += struct.pack("<11sc4xBB14x", name.encode("ascii"), ftype.encode("ascii"), length, decimals)
    out += b"\r"
    for i, row in enumerate(rows):
        out += b"*" if i in deleted else b" "
        for (name, ftype, length, decimals), value in zip(fields, row):
            if value is None:
                text = ""
            elif ftype == "N":
                text = f"{value:.{decimals}f}" if decimals else str(int(value))
            else:
                text = str(value)
            raw = text.encode("utf-8")[:length]
            out += raw.rjust(length) if ftype == "N" else raw.ljust(length)
    out += b"\x1a"
    Path(path).write_bytes(bytes(out))


def make_scenario(folder, tracks, pras, risk, region="R", scenario="D_75-55_prox0_rel2.3m"):
    """Create <folder>/<scenario>/ with tracks, pra and risk tables (only the .shp/.dbf pair).

    tracks: [(pra_elev, pra_aspdeg)]       numeric
    pras:   [(elev_med, aspect_deg)]       stored as text, like in the real data
    risk:   [(saf_class, max_ppr, pra_elev, pra_aspct)]
    Returns the scenario directory.
    """
    sdir = Path(folder) / scenario
    (sdir / "risk_assessment").mkdir(parents=True)
    stem = scenario.replace(".", "_")

    write_dbf(sdir / f"tracks_{region}_{stem}.dbf",
              [("pra_elev", "N", 12, 3), ("pra_aspdeg", "N", 6, 0)], tracks)
    (sdir / f"tracks_{region}_{stem}.shp").touch()

    write_dbf(sdir / f"pra_{region}_{stem}.dbf",
              [("elev_med", "C", 20, 0), ("aspect_deg", "C", 20, 0)],
              [tuple(None if v is None else str(v) for v in r) for r in pras])
    (sdir / f"pra_{region}_{stem}.shp").touch()

    write_dbf(sdir / "risk_assessment" / f"risk_{region}_{stem}.dbf",
              [("saf_class", "C", 4, 0), ("max_ppr", "N", 12, 3), ("pra_elev", "N", 12, 3), ("pra_aspct", "C", 4, 0)],
              risk)
    (sdir / "risk_assessment" / f"risk_{region}_{stem}.shp").touch()
    return sdir
