"""
Seed grants from a JSON file into the running backend via the public API.

The backend's POST /grants endpoint already dedupes by source_url (see
GrantService.create), so re-running this script is safe — duplicates are
silently returned as the existing record.

Usage:
    python scripts/seed_grants.py scripts/seed_data/new_grants_2026_05_14.json \
        --base-url http://2.134.15.37/api \
        --username admin --password ENV:ADMIN_PASSWORD

Auth credentials can come from --username/--password flags or env vars
ADMIN_USERNAME/ADMIN_PASSWORD. Prefix a value with ENV: to indicate an env var.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def resolve(value: str) -> str:
    if value and value.startswith("ENV:"):
        return os.environ.get(value[4:], "")
    return value


def login(client: httpx.Client, username: str, password: str) -> str:
    resp = client.post(
        "/auth/login",
        data={"username": username, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def existing_source_urls(client: httpx.Client, headers: dict) -> set[str]:
    """Pull all known source_urls so we can skip locally without hammering the API."""
    urls: set[str] = set()
    page = 1
    size = 100
    while True:
        resp = client.get(
            "/grants",
            params={"page": page, "size": size},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        for item in items:
            url = item.get("source_url")
            if url:
                urls.add(url)
        if page * size >= data.get("total", 0) or not items:
            break
        page += 1
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", help="Path to grants JSON (list of dicts)")
    ap.add_argument("--base-url", default=os.environ.get("BACKEND_URL", "http://2.134.15.37/api"))
    ap.add_argument("--username", default=os.environ.get("ADMIN_USERNAME", "admin"))
    ap.add_argument("--password", default="ENV:ADMIN_PASSWORD")
    ap.add_argument("--dry-run", action="store_true", help="Don't post — just show what would happen")
    args = ap.parse_args()

    username = resolve(args.username)
    password = resolve(args.password)
    if not password:
        print("error: no password (set ADMIN_PASSWORD or pass --password)", file=sys.stderr)
        sys.exit(2)

    grants = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    print(f"Loaded {len(grants)} grants from {args.json_path}")

    with httpx.Client(base_url=args.base_url) as client:
        token = login(client, username, password)
        headers = {"Authorization": f"Bearer {token}"}

        known = existing_source_urls(client, headers)
        print(f"Backend currently has {len(known)} unique source URLs")

        to_create = [g for g in grants if g.get("source_url") not in known]
        already = len(grants) - len(to_create)
        print(f"  {already} already present (skip), {len(to_create)} new to create")

        if args.dry_run:
            for g in to_create[:5]:
                print("  +", g["title"], "—", g["source_url"])
            if len(to_create) > 5:
                print(f"  ... and {len(to_create) - 5} more")
            return

        created = failed = 0
        for g in to_create:
            try:
                resp = client.post("/grants", json=g, headers=headers, timeout=20)
                if resp.status_code in (200, 201):
                    created += 1
                else:
                    failed += 1
                    print(f"  ! {resp.status_code} {g['title']}: {resp.text[:200]}")
            except Exception as e:
                failed += 1
                print(f"  ! {g['title']}: {e}")

        print(f"Done: {created} created, {failed} failed, {already} skipped as duplicates")


if __name__ == "__main__":
    main()
