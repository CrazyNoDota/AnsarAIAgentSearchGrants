"""Orchestrate: open page → detect fields → fill → screenshot → (optionally) submit."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from filler.browser import open_page
from filler.detector import FieldInfo, detect_fields
from filler.mapper import map_field
from storage import db as storage

log = logging.getLogger(__name__)

# Callback the bot layer provides: ask user a question, return their answer.
AskFn = Callable[[str, list[str] | None], Awaitable[str]]


@dataclass
class FillResult:
    success: bool
    screenshot: bytes | None
    filled: dict[str, str]       # selector → value actually filled
    skipped: list[str]            # field display names we couldn't map/ask
    error: str | None = None


async def _fill_input(page: Page, field: FieldInfo, value: str) -> bool:
    try:
        locator = page.locator(field.selector).first
        await locator.wait_for(state="visible", timeout=3000)

        if field.type == "checkbox":
            wanted = value.lower() in ("true", "yes", "1", "да")
            if wanted != field.checked:
                await locator.click()
            return True

        if field.type == "radio":
            # value is the option value to select
            radio = page.locator(
                f"input[type='radio'][name='{field.name}'][value='{value}']"
            ).first
            await radio.click(timeout=3000)
            return True

        if field.tag == "select":
            try:
                await locator.select_option(value=value, timeout=3000)
            except Exception:
                await locator.select_option(label=value, timeout=3000)
            return True

        await locator.fill("", timeout=3000)
        await locator.type(value, delay=30)
        return True

    except Exception as exc:
        log.warning("Could not fill %r: %s", field.selector, exc)
        return False


def _best_option(field: FieldInfo, profile_value: str) -> str:
    """For select/radio, pick the option whose label or value best matches profile_value."""
    opts = field.options or field.radio_group or []
    pv = profile_value.lower().strip()
    for opt in opts:
        if opt["value"].lower() == pv or opt["label"].lower() == pv:
            return opt["value"]
    # partial match
    for opt in opts:
        if pv in opt["label"].lower() or pv in opt["value"].lower():
            return opt["value"]
    # fallback: first non-empty option
    for opt in opts:
        if opt["value"]:
            return opt["value"]
    return profile_value


async def fill_form(
    url: str,
    telegram_id: int,
    profile: dict[str, Any],
    ask: AskFn,
    headless: bool = True,
) -> FillResult:
    filled: dict[str, str] = {}
    skipped: list[str] = []

    async with open_page(headless=headless) as page:
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            # Many pages never fully idle — domcontentloaded is fine
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            return FillResult(False, None, {}, [], error=f"Не удалось открыть страницу: {exc}")

        # Detect captcha before wasting time
        page_text = (await page.content()).lower()
        if "recaptcha" in page_text or "hcaptcha" in page_text:
            screenshot = await page.screenshot(type="png", full_page=False)
            return FillResult(
                False,
                screenshot,
                {},
                [],
                error="На странице есть капча. Реши её сам и нажми /register снова.",
            )

        fields = await detect_fields(page)

        # Skip pages without forms (might be login-gated, wrong URL, etc.)
        if not fields:
            screenshot = await page.screenshot(type="png", full_page=False)
            return FillResult(
                False,
                screenshot,
                {},
                [],
                error="Форма не найдена. Возможно нужна авторизация или ссылка ведёт не туда.",
            )

        for field in fields:
            profile_key = await map_field(field)
            value: str | None = None

            if profile_key and profile.get(profile_key):
                value = str(profile[profile_key])
                # Adapt value to select/radio options
                if field.options or field.radio_group:
                    value = _best_option(field, value)

            else:
                # Check if user already answered this field before
                cached = await storage.get_custom_answer(telegram_id, field.signature)
                if cached:
                    value = cached
                else:
                    # Need to ask
                    options = None
                    if field.options:
                        options = [o["label"] or o["value"] for o in field.options if o["value"]]
                    elif field.radio_group:
                        options = [o["label"] or o["value"] for o in field.radio_group]

                    try:
                        answer = await asyncio.wait_for(
                            ask(field.display, options), timeout=120
                        )
                    except asyncio.TimeoutError:
                        skipped.append(field.display)
                        continue

                    if answer.strip() in ("-", "skip", "пропустить"):
                        skipped.append(field.display)
                        continue

                    # If select/radio, map label → value
                    if field.options or field.radio_group:
                        answer = _best_option(field, answer)

                    await storage.save_custom_answer(
                        telegram_id, field.signature, field.display, answer
                    )
                    value = answer

            if value is not None:
                ok = await _fill_input(page, field, value)
                if ok:
                    filled[field.display] = value
                else:
                    skipped.append(field.display)

        screenshot = await page.screenshot(type="png", full_page=False)
        return FillResult(True, screenshot, filled, skipped)


async def submit_form(
    url: str,
    telegram_id: int,
    profile: dict[str, Any],
    ask: AskFn,
    headless: bool = True,
) -> FillResult:
    """Fill and then click submit, return post-submit screenshot."""
    filled: dict[str, str] = {}
    skipped: list[str] = []

    async with open_page(headless=headless) as page:
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            return FillResult(False, None, {}, [], error=f"Не удалось открыть страницу: {exc}")

        page_text = (await page.content()).lower()
        if "recaptcha" in page_text or "hcaptcha" in page_text:
            screenshot = await page.screenshot(type="png", full_page=False)
            return FillResult(False, screenshot, {}, [],
                              error="Капча. Реши вручную и попробуй снова.")

        fields = await detect_fields(page)
        if not fields:
            screenshot = await page.screenshot(type="png", full_page=False)
            return FillResult(False, screenshot, {}, [],
                              error="Форма не найдена на странице.")

        for field in fields:
            profile_key = await map_field(field)
            value: str | None = None

            if profile_key and profile.get(profile_key):
                value = str(profile[profile_key])
                if field.options or field.radio_group:
                    value = _best_option(field, value)
            else:
                cached = await storage.get_custom_answer(telegram_id, field.signature)
                if cached:
                    value = cached
                else:
                    options = None
                    if field.options:
                        options = [o["label"] or o["value"] for o in field.options if o["value"]]
                    elif field.radio_group:
                        options = [o["label"] or o["value"] for o in field.radio_group]
                    try:
                        answer = await asyncio.wait_for(ask(field.display, options), timeout=120)
                    except asyncio.TimeoutError:
                        skipped.append(field.display)
                        continue
                    if answer.strip() in ("-", "skip", "пропустить"):
                        skipped.append(field.display)
                        continue
                    if field.options or field.radio_group:
                        answer = _best_option(field, answer)
                    await storage.save_custom_answer(
                        telegram_id, field.signature, field.display, answer
                    )
                    value = answer

            if value is not None:
                ok = await _fill_input(page, field, value)
                if ok:
                    filled[field.display] = value
                else:
                    skipped.append(field.display)

        # Click submit
        submit = page.locator(
            "button[type=submit], input[type=submit], button:has-text('Register'), "
            "button:has-text('Submit'), button:has-text('Sign up'), "
            "button:has-text('Зарегистрироваться'), button:has-text('Отправить')"
        ).first
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
                await submit.click(timeout=5_000)
        except Exception:
            # Some forms use AJAX — just wait a moment
            await page.wait_for_timeout(3000)

        screenshot = await page.screenshot(type="png", full_page=False)
        return FillResult(True, screenshot, filled, skipped)
