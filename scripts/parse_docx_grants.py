"""
Parse a `.docx` of grants (Aidar's curated list) into JSON for the seed script.

Run once when a fresh list arrives:
    python scripts/parse_docx_grants.py "<path to .docx>" scripts/seed_data/<name>.json

The .docx is a single CSV-shaped table with header:
    Название программы,Тип,Организация,Сфера,Страна,Дедлайн,Сумма,
    Доступность,Место реализации,Ключевые требования,Сайт,Статус
"""
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from docx import Document

CATEGORY_MAP = {
    "R&D Grant": "Research",
    "Грант": "Grant",
    "Грант для НКО": "NGO",
    "Грант для стартапов студентов": "Student",
    "Грант (non-equity)": "Grant",
    "Инвестиции + Грант": "Investment",
    "Инвестиции + грант": "Investment",
    "Инвестиции": "Investment",
    "Акселератор": "Accelerator",
    "R&D/Акселератор": "Accelerator",
    "R&D/Венчур": "Accelerator",
    "Конкурс": "Competition",
    "Облачные кредиты": "Cloud Credits",
    "Стипендия": "Fellowship",
    "Постдок": "Fellowship",
    "Государственная программа": "Government",
}


def parse_deadline(raw: str):
    """Return (iso_date_or_none, raw_for_description)."""
    if not raw:
        return None, ""
    raw = raw.strip()
    # Standard "YYYY-MM-DD 00:00:00"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        try:
            datetime.strptime(m.group(1), "%Y-%m-%d")
            return m.group(1), raw
        except ValueError:
            pass
    return None, raw


def build_grant(row: dict) -> dict | None:
    title = (row.get("Название программы") or "").strip()
    url = (row.get("Сайт") or "").strip()
    if not title or not url:
        return None

    deadline_iso, deadline_raw = parse_deadline(row.get("Дедлайн") or "")
    type_ru = (row.get("Тип") or "").strip()
    org = (row.get("Организация") or "").strip()
    industry = (row.get("Сфера") or "").strip()
    country = (row.get("Страна") or "").strip()
    amount = (row.get("Сумма") or "").strip()
    avail = (row.get("Доступность") or "").strip()
    place = (row.get("Место реализации") or "").strip()
    req = (row.get("Ключевые требования") or "").strip()

    category = CATEGORY_MAP.get(type_ru, type_ru or "Other")

    # Build description from the rich Russian fields
    desc_parts = []
    if type_ru:
        desc_parts.append(f"Тип: {type_ru}")
    if industry:
        desc_parts.append(f"Сфера: {industry}")
    if req:
        desc_parts.append(f"Ключевые требования: {req}")
    if place:
        desc_parts.append(f"Место реализации: {place}")
    if not deadline_iso and deadline_raw:
        desc_parts.append(f"Дедлайн: {deadline_raw}")

    elig_parts = []
    if avail:
        elig_parts.append(avail)
    if req:
        elig_parts.append(req)

    return {
        "title": title[:512],
        "description": "\n".join(desc_parts)[:2000],
        "organization": org[:255],
        "country": country[:255],
        "category": category[:255],
        "deadline": deadline_iso,
        "source_url": url[:2000],
        "application_url": url[:2000],
        "grant_amount": amount[:255] or None,
        "eligibility": " — ".join(elig_parts)[:1000] or None,
        "industry": industry[:255] or None,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python parse_docx_grants.py <docx> <out.json>", file=sys.stderr)
        sys.exit(1)

    docx_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document(str(docx_path))
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    if not lines:
        print("Empty document", file=sys.stderr)
        sys.exit(1)

    buf = io.StringIO("\n".join(lines))
    reader = csv.DictReader(buf)
    grants = []
    skipped = 0
    for row in reader:
        g = build_grant(row)
        if g:
            grants.append(g)
        else:
            skipped += 1

    out_path.write_text(json.dumps(grants, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Parsed {len(grants)} grants, skipped {skipped}. Wrote {out_path}")


if __name__ == "__main__":
    main()
