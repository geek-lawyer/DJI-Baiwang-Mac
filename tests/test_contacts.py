from pathlib import Path

from baiwang_mac.contacts import import_csv, import_vcard


def test_import_csv(tmp_path: Path):
    path = tmp_path / "contacts.csv"
    path.write_text("name,phone\n测试联系人,+8613800000000\n", encoding="utf-8")
    contacts = import_csv(path)
    assert contacts[0].name == "测试联系人"
    assert contacts[0].phone == "+8613800000000"


def test_import_vcard(tmp_path: Path):
    path = tmp_path / "contacts.vcf"
    path.write_text("BEGIN:VCARD\nVERSION:3.0\nFN:测试联系人\nTEL;TYPE=CELL:+8613800000000\nEND:VCARD\n", encoding="utf-8")
    contacts = import_vcard(path)
    assert contacts[0].phone == "+8613800000000"

