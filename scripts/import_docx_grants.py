"""
One-shot import of grants from the new data.docx file into the backend API.
Run: python scripts/import_docx_grants.py
"""
import sys, zipfile, xml.etree.ElementTree as ET, re, csv, io, json
import urllib.request, urllib.parse

DOCX_PATH = r"C:\Users\Jalil\Downloads\Telegram Desktop\new data.docx"
API_BASE   = "https://ansar-grants-api.vercel.app"
USERNAME   = "admin"
PASSWORD   = "AnsarAdmin2026!"

# ── 1. Extract text from docx ────────────────────────────────────────────────
def extract_docx_rows(path: str) -> list[list[str]]:
    with zipfile.ZipFile(path) as z:
        xml_bytes = z.read("word/document.xml")
    tree = ET.fromstring(xml_bytes)
    rows = []
    for para in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = [
            t.text
            for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            if t.text
        ]
        line = "".join(parts).strip()
        if line:
            rows.append(list(csv.reader([line]))[0])
    return rows

# ── 2. Parse date ────────────────────────────────────────────────────────────
def parse_deadline(raw: str) -> str | None:
    if not raw or "rolling" in raw.lower() or "постоянно" in raw.lower():
        return None
    if "осень" in raw.lower() or "плановый" in raw.lower() or raw.strip().startswith("Осень"):
        return None
    # "2026-05-06 00:00:00"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    return None

# ── 3. Auth ──────────────────────────────────────────────────────────────────
def get_token() -> str:
    data = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    req  = urllib.request.Request(f"{API_BASE}/auth/login", data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]

# ── 4. Insert grant ──────────────────────────────────────────────────────────
def insert_grant(token: str, grant: dict) -> str:
    body = json.dumps(grant).encode()
    req  = urllib.request.Request(
        f"{API_BASE}/grants",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return "new" if r.status == 201 else "exists"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 409 or "already exists" in body or "unique" in body.lower():
            return "exists"
        return f"error {e.code}: {body[:80]}"

# ── 5. Main ──────────────────────────────────────────────────────────────────
def main():
    rows = extract_docx_rows(DOCX_PATH)
    if not rows:
        print("No rows found in docx"); sys.exit(1)

    # First row is header
    header, data_rows = rows[0], rows[1:]
    print(f"Header: {header}")
    print(f"Rows  : {len(data_rows)}")

    token = get_token()
    print(f"Authenticated ✓\n")

    new_count = skip_count = err_count = 0

    for i, row in enumerate(data_rows):
        if len(row) < 11:
            print(f"  [{i+1}] SKIP (short row): {row}")
            continue

        title    = row[0].strip()
        typ      = row[1].strip()   # e.g. "R&D Grant", "Акселератор"
        org      = row[2].strip()
        sphere   = row[3].strip()   # main category/field
        country  = row[4].strip()
        deadline = parse_deadline(row[5].strip())
        amount   = row[6].strip()
        access   = row[7].strip()
        location = row[8].strip()
        req      = row[9].strip()
        url      = row[10].strip()

        description = (
            f"Тип: {typ}\n"
            f"Сумма: {amount}\n"
            f"Доступность: {access}\n"
            f"Место реализации: {location}\n"
            f"Ключевые требования: {req}"
        )

        grant = {
            "title":       title,
            "organization": org,
            "country":     country,
            "category":    f"{typ} — {sphere}" if sphere else typ,
            "deadline":    deadline,
            "description": description,
            "source_url":  url,
        }

        result = insert_grant(token, grant)

        if result == "new":
            new_count += 1
            print(f"  [{i+1}] ✅ {title}")
        elif result == "exists":
            skip_count += 1
            print(f"  [{i+1}] ⏭  {title} (already exists)")
        else:
            err_count += 1
            print(f"  [{i+1}] ❌ {title} → {result}")

    print(f"\n{'='*50}")
    print(f"Done: {new_count} added, {skip_count} skipped, {err_count} errors")

if __name__ == "__main__":
    main()
