import pytest

from alarm_core.dbf import read_dbf_columns, to_number
from dbf_fixture import write_dbf

FIELDS = [("id", "N", 8, 0), ("elev", "N", 12, 3), ("name", "C", 10, 0)]


def test_reads_numbers_and_text(tmp_path):
    write_dbf(tmp_path / "t.dbf", FIELDS, [(1, 10.5, "abc"), (2, None, "x y"), (3, 300.25, "")])
    cols, n = read_dbf_columns(tmp_path / "t.dbf", ["id", "elev", "name"])
    assert n == 3
    assert cols["id"] == [1.0, 2.0, 3.0]
    assert cols["elev"] == [10.5, None, 300.25]      # blank numeric -> None
    assert cols["name"] == ["abc", "x y", ""]


def test_field_names_are_case_insensitive_and_keys_keep_requested_spelling(tmp_path):
    write_dbf(tmp_path / "t.dbf", FIELDS, [(1, 1.0, "a")])
    cols, _ = read_dbf_columns(tmp_path / "t.dbf", ["ELEV"])
    assert list(cols) == ["ELEV"] and cols["ELEV"] == [1.0]


def test_deleted_records_are_skipped(tmp_path):
    write_dbf(tmp_path / "t.dbf", FIELDS, [(1, 1.0, "a"), (2, 2.0, "b"), (3, 3.0, "c")], deleted={1})
    cols, n = read_dbf_columns(tmp_path / "t.dbf", ["id"])
    assert n == 2 and cols["id"] == [1.0, 3.0]


def test_missing_field_raises(tmp_path):
    write_dbf(tmp_path / "t.dbf", FIELDS, [(1, 1.0, "a")])
    with pytest.raises(KeyError, match="nope"):
        read_dbf_columns(tmp_path / "t.dbf", ["nope"])


def test_empty_table(tmp_path):
    write_dbf(tmp_path / "t.dbf", FIELDS, [])
    cols, n = read_dbf_columns(tmp_path / "t.dbf", ["id"])
    assert n == 0 and cols["id"] == []


@pytest.mark.parametrize("value, expected", [
    (5, 5.0), ("12.5", 12.5), (" 7 ", 7.0), (None, None), ("", None), ("abc", None), ("-1", -1.0)])
def test_to_number(value, expected):
    assert to_number(value) == expected
