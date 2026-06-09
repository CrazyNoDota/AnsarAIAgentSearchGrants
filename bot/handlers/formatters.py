"""Grant card formatter for Telegram messages."""
from datetime import date

STATUS_RU = {
    "pending": "НА РАССМОТРЕНИИ",
    "approved": "ОДОБРЕН",
    "rejected": "ОТКЛОНЁН",
}


def format_grant(grant: dict, index: int = 1, total: int = 1) -> str:
    """Render a grant as a clean Telegram HTML message card."""
    deadline = grant.get("deadline")
    if deadline:
        try:
            d = date.fromisoformat(deadline)
            days_left = (d - date.today()).days
            if days_left < 0:
                deadline_str = f"⚠️ {deadline} (истёк)"
            elif days_left == 0:
                deadline_str = f"🔴 {deadline} (СЕГОДНЯ)"
            elif days_left <= 3:
                deadline_str = f"🔴 {deadline} (осталось {days_left} дн.)"
            elif days_left <= 7:
                deadline_str = f"🟡 {deadline} (осталось {days_left} дн.)"
            elif days_left <= 14:
                deadline_str = f"🔵 {deadline} (осталось {days_left} дн.)"
            else:
                deadline_str = f"🟢 {deadline} (осталось {days_left} дн.)"
        except ValueError:
            deadline_str = deadline
    else:
        deadline_str = "Не указан"

    ai_score = grant.get("ai_score", 0)
    score_pct = min(100, max(0, int(ai_score))) if isinstance(ai_score, (int, float)) else 0

    lines = [
        f"📌 <b>Грант {index}/{total}</b>",
        "",
        f"<b>{grant.get('title', 'Без названия')}</b>",
        "",
        f"🏢 <b>Организация:</b> {grant.get('organization') or '—'}",
        f"🌍 <b>Страна:</b> {grant.get('country') or '—'}",
        f"🏷 <b>Категория:</b> {grant.get('category') or '—'}",
    ]

    if grant.get("industry"):
        lines.append(f"🏭 <b>Отрасль:</b> {grant['industry']}")

    if grant.get("startup_stage"):
        lines.append(f"📈 <b>Стадия:</b> {grant['startup_stage']}")

    amount = grant.get("grant_amount") or "Не указана"
    lines.append(f"💰 <b>Сумма:</b> {amount}")

    lines.append(f"📅 <b>Дедлайн:</b> {deadline_str}")

    if score_pct > 0:
        bar_len = min(10, score_pct // 10)
        bar = "▓" * bar_len + "░" * (10 - bar_len)
        lines.append(f"🤖 <b>Оценка ИИ:</b> {bar} {score_pct}%")

    description = grant.get("description", "")
    if description:
        truncated = description[:280] + "…" if len(description) > 280 else description
        lines += ["", f"📝 {truncated}"]

    if grant.get("eligibility"):
        elig = grant["eligibility"][:150] + "…" if len(grant["eligibility"]) > 150 else grant["eligibility"]
        lines += ["", f"✅ <b>Кто может подать:</b> {elig}"]

    source_url = grant.get("source_url", "")
    app_url = grant.get("application_url", "")
    if source_url:
        lines += ["", f'🔗 <a href="{source_url}">Открыть грант</a>']
    if app_url and app_url != source_url:
        lines.append(f'📋 <a href="{app_url}">Подать заявку</a>')

    status = grant.get("status", "pending")
    lines += [
        "",
        f"🆔 ID: <code>{grant.get('id')}</code>  |  Статус: <b>{STATUS_RU.get(status, status.upper())}</b>",
    ]

    return "\n".join(lines)
