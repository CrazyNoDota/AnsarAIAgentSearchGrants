"""Форматтер сообщений о грантах для Telegram."""
from datetime import date

STATUS_RU = {
    "pending": "НА РАССМОТРЕНИИ",
    "approved": "ОДОБРЕНО",
    "rejected": "ОТКЛОНЕНО",
}


def format_grant(grant: dict, index: int = 1, total: int = 1) -> str:
    """Преобразует грант в HTML-сообщение для Telegram."""
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
                deadline_str = f"🔴 {deadline} (осталось дн.: {days_left})"
            elif days_left <= 7:
                deadline_str = f"🟡 {deadline} (осталось дн.: {days_left})"
            else:
                deadline_str = f"🟢 {deadline} (осталось дн.: {days_left})"
        except ValueError:
            deadline_str = deadline
    else:
        deadline_str = "не указан"

    ai_score = grant.get("ai_score", 0)
    score_bar = "⭐" * min(5, max(0, int(ai_score / 10))) if ai_score > 0 else ""

    lines = [
        f"📋 <b>Грант {index}/{total}</b>",
        "",
        f"<b>{grant.get('title', 'Без названия')}</b>",
        "",
        f"🏢 <b>Организация:</b> {grant.get('organization') or 'не указана'}",
        f"🌍 <b>Страна:</b> {grant.get('country') or 'не указана'}",
        f"🏷 <b>Категория:</b> {grant.get('category') or 'не указана'}",
        f"📅 <b>Срок:</b> {deadline_str}",
    ]

    if score_bar:
        lines.append(f"🤖 <b>AI-рейтинг:</b> {score_bar} ({ai_score:.1f})")

    description = grant.get("description", "")
    if description:
        truncated = description[:300] + "..." if len(description) > 300 else description
        lines += ["", f"📝 {truncated}"]

    source_url = grant.get("source_url", "")
    if source_url:
        lines += ["", f'🔗 <a href="{source_url}">Открыть грант</a>']

    status = grant.get("status", "pending")
    lines += [
        "",
        f"🆔 ID гранта: <code>{grant.get('id')}</code>",
        f"📊 Статус: <b>{STATUS_RU.get(status, status.upper())}</b>",
    ]

    return "\n".join(lines)
