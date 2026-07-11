import pytest

from baiwang_mac.backend import BaiwangController, BaiwangError, decode_ucs2, encode_ucs2, format_sms_timestamp, normalize_phone


def test_ucs2_round_trip():
    text = "测试短信"
    assert decode_ucs2(encode_ucs2(text)) == text


def test_phone_normalization_uses_fictional_number():
    assert normalize_phone("+86 138 0000 0000") == "+8613800000000"


def test_phone_rejects_unsafe_text():
    with pytest.raises(BaiwangError):
        normalize_phone("not-a-number")


def test_parse_ucs2_message():
    response = (
        '+CMGL: 7,"00520045004300200052004500410044","002B0038003600310033003800300030003000300030003000300030","26/07/11,19:00:00+32"\r\n'
        '6D4B8BD577ED4FE1\r\nOK\r\n'
    )
    messages = BaiwangController._parse_messages(response)
    assert len(messages) == 1
    assert messages[0].index == 7
    assert messages[0].sender == "+8613800000000"
    assert messages[0].body == "测试短信"
    assert messages[0].timestamp == "2026-07-11 19:00:00"


def test_format_sms_timestamp():
    assert format_sms_timestamp("26/07/11,18:49:01+32") == "2026-07-11 18:49:01"


def test_operator_profile_mapping():
    available = ("VoLTE_OPNMKT_CT", "Volte_OpenMkt-Commercial-CMCC", "CU-VoLTE")
    assert BaiwangController._operator_profile("CHN-CT", available) == "VoLTE_OPNMKT_CT"
    assert BaiwangController._operator_profile("CHINA MOBILE", available) == "Volte_OpenMkt-Commercial-CMCC"
    assert BaiwangController._operator_profile("CHN-CU", available) == "CU-VoLTE"
    assert BaiwangController._operator_profile("Unknown", available) is None
