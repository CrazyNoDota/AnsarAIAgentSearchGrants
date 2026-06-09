"""
Phase 4 — Email notification channel (ALONGSIDE Telegram, not a replacement).

Sends deadline reminders (and optional readiness nudges) over SMTP using the
Python standard library only (``smtplib`` / ``email``) — no new dependency.

DESIGN / CONVENTIONS (mirrors the Telegram path):
- Credentials load from settings / .env ONLY (never hardcoded): SMTP_HOST,
  SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_TLS/SSL, EMAIL_FROM.
- Degrades gracefully: when email is unconfigured (no host/sender) the service
  reports ``available is False`` and ``send_email`` logs + returns False instead
  of raising — exactly how the Telegram alert path skips when the bot token is
  missing.
- The blocking ``smtplib`` call is run in a thread (``asyncio.to_thread``) so it
  never blocks the event loop.
- Message construction is a pure, unit-testable function (``build_message``); the
  actual transport (``_smtp_send``) is isolated so tests can stub it without a
  real network/SMTP server.
- Body building for deadline reminders is pure (``render_deadline_email``) so the
  same content can be asserted offline.
"""
from __future__ import annotations

import asyncio
import logging
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional
from urllib.parse import urlsplit

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Bound the recipient list per call so a misconfiguration can't fan out forever.
MAX_RECIPIENTS_PER_SEND = 500
SMTP_TIMEOUT_SECONDS = 20


def _is_single_recipient_address(addr: str) -> bool:
    """Small send-time guard against malformed/imported recipient strings."""
    if not isinstance(addr, str):
        return False
    if not addr:
        return False
    stripped = addr.strip()
    if not stripped or stripped.count("@") != 1:
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in addr):
        return False
    if any(ch.isspace() for ch in stripped):
        return False
    if any(ch in stripped for ch in ",;<>[]()\""):
        return False
    local, domain = stripped.split("@", 1)
    return bool(local and domain)


def _http_url(url: str) -> str:
    url = url.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return ""
    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return ""


def build_message(
    *,
    sender: str,
    to_addr: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> EmailMessage:
    """Construct a single-recipient email (pure — no network).

    Always sets a plain-text body; attaches an HTML alternative when provided.
    """
    msg = EmailMessage()
    msg["From"] = formataddr(("Ansar Grant Agent", sender))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def render_deadline_email(items: list[dict]) -> tuple[str, str, str]:
    """Render the subject + (text, html) bodies for a batch of deadline items.

    Pure function — `items` are the same dicts the deadlines route already builds
    ({title, deadline, days_left, source_url}). Returns (subject, text, html).
    """
    n = len(items)
    subject = (
        f"Grant deadline reminder: {n} upcoming deadline"
        f"{'s' if n != 1 else ''}"
    )

    text_lines = ["Upcoming grant deadlines:\n"]
    html_rows = []
    for it in items:
        title = str(it.get("title", "(untitled)"))
        deadline = str(it.get("deadline", "?"))
        days = it.get("days_left", "?")
        url = _http_url(str(it.get("source_url") or ""))
        text_lines.append(
            f"- {title}\n  Deadline: {deadline} ({days} day(s) left)"
            + (f"\n  {url}" if url else "")
        )
        link = (
            f'<a href="{_html_escape(url)}">Open grant</a>' if url else ""
        )
        html_rows.append(
            f"<li><strong>{_html_escape(title)}</strong><br>"
            f"Deadline: <strong>{_html_escape(deadline)}</strong> "
            f"({_html_escape(str(days))} day(s) left)"
            + (f"<br>{link}" if link else "")
            + "</li>"
        )

    text_body = "\n".join(text_lines)
    html_body = (
        "<html><body>"
        "<h3>Upcoming grant deadlines</h3>"
        f"<ul>{''.join(html_rows)}</ul>"
        "<p style='color:#888;font-size:12px'>Ansar Grant Agent</p>"
        "</body></html>"
    )
    return subject, text_body, html_body


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class EmailService:
    """SMTP email sender. Safe to instantiate even when email is unconfigured."""

    def __init__(self) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        """True only when a host AND a sender address are configured."""
        return self._settings.use_email

    async def send_email(
        self,
        to_addr: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> bool:
        """Send one email. Returns True on success, False on skip/failure.

        Never raises for an unconfigured channel or a transport error — logs and
        returns False so a cron/reminder run is not aborted by email problems.
        """
        if not self.available:
            logger.warning("Email not configured (SMTP_HOST/EMAIL_FROM) — skipping send")
            return False
        if not to_addr:
            logger.warning("send_email called with empty recipient — skipping")
            return False

        if not _is_single_recipient_address(to_addr):
            logger.warning("send_email called with invalid recipient — skipping")
            return False
        to_addr = to_addr.strip()
        try:
            msg = build_message(
                sender=self._settings.email_sender,
                to_addr=to_addr,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
            await asyncio.to_thread(self._smtp_send, msg)
            return True
        except Exception as e:  # construction/transport/auth/timeout must not crash the run
            logger.error("Email send to %s failed: %s", to_addr, e)
            return False

    async def send_bulk(
        self,
        recipients: list[str],
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> int:
        """Send the same message to many recipients. Returns count delivered.

        Each recipient gets its own message (no shared To/BCC leak). Failures are
        logged per-recipient and do not abort the batch.
        """
        if not self.available:
            logger.warning("Email not configured — skipping bulk send")
            return 0
        # De-duplicate + drop empties, then bound the fan-out.
        unique = [r for r in dict.fromkeys(recipients) if r]
        if len(unique) > MAX_RECIPIENTS_PER_SEND:
            logger.warning(
                "Email bulk send capped at %d recipients (%d requested)",
                MAX_RECIPIENTS_PER_SEND,
                len(unique),
            )
            unique = unique[:MAX_RECIPIENTS_PER_SEND]

        sent = 0
        for addr in unique:
            try:
                if await self.send_email(addr, subject, text_body, html_body):
                    sent += 1
            except Exception as e:
                logger.error("Email bulk send to %s failed: %s", addr, e)
        return sent

    # ── Transport (isolated so tests can stub it) ──────────────────────────

    def _smtp_send(self, msg: EmailMessage) -> None:
        """Blocking SMTP delivery. Lazy stdlib import; honours TLS/SSL settings."""
        import smtplib

        s = self._settings
        if s.smtp_use_ssl:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        try:
            if s.smtp_use_tls and not s.smtp_use_ssl:
                server.starttls()
            if s.smtp_user and s.smtp_password:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
