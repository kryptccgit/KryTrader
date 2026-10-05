from __future__ import annotations

import service


def test_naive_sqlite_string_gets_t_and_z():
    assert service._iso_utc("2024-01-02 03:04:05") == "2024-01-02T03:04:05Z"


def test_already_zulu_is_left_alone():
    assert service._iso_utc("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05Z"


def test_offset_timestamp_is_not_double_tagged():
    s = "2024-01-02T03:04:05+00:00"
    assert service._iso_utc(s) == s


def test_empty_and_none_pass_through():
    assert service._iso_utc("") == ""
    assert service._iso_utc(None) is None
