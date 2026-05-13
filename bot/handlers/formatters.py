"""Grant card formatter for Telegram messages."""
from datetime import date

STATUS_RU = {"pending": "PENDING", "approved": "APPROVED", "rejected": "REJECTED"}


def format_grant(grant: dict, index: int = 1, total: int = 1) -> str:
    """Render a grant as a clean Telegram HTML message card."""
    deadline = grant.get("deadline")
    if deadline:
        try:
            d = date.fromisoformat(deadline)
            days_left = (d - date.today()).days
            if days_left < 0:
                deadline_str = f"⚠️ {deadline} (expired)"
            elif days_left == 0:
                deadline_str = f"🔴 {deadline} (TODAY)"
            elif days_left <= 3:
                deadline_str = f"🔴 {deadline} ({days_left}d left)"
            elif days_left <= 7:
                deadline_str = f"🟡 {deadline} ({days_left}d left)"
            elif days_left <= 14:
                deadline_str = f"🔵 {deadline} ({days_left}d left)"
            else:
                deadline_str = f"🟢 {deadline} ({days_left}d left)"
        except ValueError:
            deadline_str = deadline
    else:
        deadline_str = "Not specified"

    ai_score = grant.get("ai_score", 0)
    score_pct = min(100, max(0, int(ai_score))) if isinstance(ai_score, (int, float)) else 0

    lines = [
        f"📌 <b>Grant {index}/{total}</b>",
        "",
        f"<b>{grant.get('title', 'Untitled')}</b>",
        "",
        f"🏢 <b>Org:</b> {grant.get('organization') or 'N/A'}",
        f"🌍 <b>Country:</b> {grant.get('country') or 'N/A'}",
        f"🏷 <b>Category:</b> {grant.get('category') or 'N/A'}",
    ]

    if grant.get("industry"):
        lines.append(f"🏭 <b>Industry:</b> {grant['industry']}")

    if grant.get("startup_stage"):
        lines.append(f"📈 <b>Stage:</b> {grant['startup_stage']}")

    amount = grant.get("grant_amount") or "Not specified"
    lines.append(f"💰 <b>Amount:</b> {amount}")

    lines.append(f"📅 <b>Deadline:</b> {deadline_str}")

    if score_pct > 0:
        bar_len = min(10, score_pct // 10)
        bar = "▓" * bar_len + "░" * (10 - bar_len)
        lines.append(f"🤖 <b>AI Score:</b> {bar} {score_pct}%")

    description = grant.get("description", "")
    if description:
        truncated = description[:280] + "…" if len(description) > 280 else description
        lines += ["", f"📝 {truncated}"]

    if grant.get("eligibility"):
        elig = grant["eligibility"][:150] + "…" if len(grant["eligibility"]) > 150 else grant["eligibility"]
        lines += ["", f"✅ <b>Eligibility:</b> {elig}"]

    source_url = grant.get("source_url", "")
    app_url = grant.get("application_url", "")
    if source_url:
        lines += ["", f'🔗 <a href="{source_url}">View Grant</a>']
    if app_url and app_url != source_url:
        lines.append(f'📋 <a href="{app_url}">Apply Here</a>')

    status = grant.get("status", "pending")
    lines += [
        "",
        f"🆔 ID: <code>{grant.get('id')}</code>  |  Status: <b>{STATUS_RU.get(status, status.upper())}</b>",
    ]

    return "\n".join(lines)
