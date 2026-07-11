from baiwang_mac.i18n import translate
from baiwang_mac.documents import PRIVACY_TEXT


def test_english_interface_translation_is_real():
    assert translate("概览", "en_US") == "Overview"
    assert translate("可以正常使用", "en_US") == "Ready to Use"
    assert translate("本次连接：02:18:36", "en_US") == "Current Session：02:18:36"
    assert translate("中国电信 · 4G LTE · 信号 90%", "en_US") == "China Telecom · 4G LTE · Signal 90%"
    assert translate("已用 38.40 GB / 100 GB", "en_US") == "Used 38.40 GB / 100 GB"


def test_traditional_chinese_translation_is_real():
    assert translate("设置", "zh_TW") == "設置"
    assert translate("未检测到 SIM 卡", "zh_TW") == "未檢測到 SIM 卡"


def test_english_help_document_is_translated():
    assert translate(PRIVACY_TEXT, "en_US").startswith("Privacy Notice")
