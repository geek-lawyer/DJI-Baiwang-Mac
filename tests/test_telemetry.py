from datetime import date

from baiwang_mac.telemetry import cycle_id, format_bytes, format_speed_pair


def test_speed_pair_uses_one_shared_byte_unit():
    down, up = format_speed_pair(1.08 * 1024 * 1024, 150 * 1024, "bytes")
    assert down == "1.08 MB/s"
    assert up == "0.15 MB/s"


def test_speed_pair_uses_one_shared_bit_unit():
    down, up = format_speed_pair(2_000_000 / 8, 250_000 / 8, "bits")
    assert down == "2.00 Mbps"
    assert up == "0.25 Mbps"


def test_speed_pair_falls_back_to_bytes():
    assert format_speed_pair(800, 120, "bytes") == ("800 B/s", "120 B/s")


def test_cycle_id_uses_previous_month_before_reset_day():
    assert cycle_id(date(2026, 7, 5), 10) == "2026-06-10"
    assert cycle_id(date(2026, 7, 15), 10) == "2026-07-10"


def test_format_bytes():
    assert format_bytes(1024**3) == "1.00 GB"
