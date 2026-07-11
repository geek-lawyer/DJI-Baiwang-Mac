from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class Contact:
    name: str
    phone: str


def import_csv(path: str | Path) -> list[Contact]:
    contacts: list[Contact] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return contacts
        lowered = {field.lower(): field for field in reader.fieldnames}
        name_key = next((lowered[key] for key in ("name", "姓名", "full name") if key in lowered), reader.fieldnames[0])
        phone_key = next((lowered[key] for key in ("phone", "mobile", "手机号", "电话") if key in lowered), None)
        if not phone_key:
            raise ValueError("CSV 需要 phone、mobile、手机号或电话列")
        for row in reader:
            name, phone = row.get(name_key, "").strip(), row.get(phone_key, "").strip()
            if phone:
                contacts.append(Contact(name or phone, phone))
    return contacts


def import_vcard(path: str | Path) -> list[Contact]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    contacts: list[Contact] = []
    for card in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", text, re.S | re.I):
        name_match = re.search(r"^FN(?:;[^:]*)?:(.*)$", card, re.M | re.I)
        name = name_match.group(1).strip() if name_match else ""
        for phone in re.findall(r"^TEL(?:;[^:]*)?:(.*)$", card, re.M | re.I):
            phone = phone.strip()
            if phone:
                contacts.append(Contact(name or phone, phone))
    return contacts


def save_contacts(path: str | Path, contacts: list[Contact]) -> None:
    Path(path).write_text(json.dumps([asdict(item) for item in contacts], ensure_ascii=False, indent=2), encoding="utf-8")


def load_contacts(path: str | Path) -> list[Contact]:
    target = Path(path)
    if not target.exists():
        return []
    return [Contact(**item) for item in json.loads(target.read_text(encoding="utf-8"))]

