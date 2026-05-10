"""
Register the Telegram bot webhook.

Run once after the API is deployed to Vercel:

    python scripts/register_telegram_webhook.py \
        --token <TELEGRAM_BOT_TOKEN> \
        --url   https://<api-project>.vercel.app/api/telegram \
        --secret <TELEGRAM_WEBHOOK_SECRET>

Or, with values pulled from your local .env:

    python scripts/register_telegram_webhook.py --from-env

To remove the webhook (e.g. switch back to polling for local dev):

    python scripts/register_telegram_webhook.py --delete --token <TOKEN>
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
import urllib.request


def _api(token: str, method: str, params: dict) -> dict:
    import json
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as r:
        return json.loads(r.read().decode())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--token")
    p.add_argument("--url")
    p.add_argument("--secret")
    p.add_argument("--from-env", action="store_true")
    p.add_argument("--delete", action="store_true")
    args = p.parse_args()

    if args.from_env:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        args.token = args.token or os.getenv("TELEGRAM_BOT_TOKEN")
        args.secret = args.secret or os.getenv("TELEGRAM_WEBHOOK_SECRET")
        # url has no canonical env var — supply via CLI

    if not args.token:
        print("ERROR: --token required (or set TELEGRAM_BOT_TOKEN with --from-env)")
        return 1

    if args.delete:
        result = _api(args.token, "deleteWebhook", {"drop_pending_updates": "true"})
        print(result)
        return 0 if result.get("ok") else 1

    if not args.url:
        print("ERROR: --url required")
        return 1

    params = {"url": args.url, "drop_pending_updates": "true"}
    if args.secret:
        params["secret_token"] = args.secret

    result = _api(args.token, "setWebhook", params)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
