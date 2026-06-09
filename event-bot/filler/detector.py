from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

# JS that walks every visible form control and collects metadata.
# Returns a list of objects we map to FieldInfo on the Python side.
_COLLECT_JS = r"""
() => {
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };

    const labelFor = (el) => {
        if (el.id) {
            const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (lbl && lbl.textContent) return lbl.textContent.trim();
        }
        let p = el.parentElement;
        while (p && p !== document.body) {
            if (p.tagName === 'LABEL' && p.textContent) return p.textContent.trim();
            p = p.parentElement;
        }
        const aria = el.getAttribute('aria-label');
        if (aria) return aria.trim();
        const labelledby = el.getAttribute('aria-labelledby');
        if (labelledby) {
            const refs = labelledby.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean);
            const text = refs.map(r => r.textContent || '').join(' ').trim();
            if (text) return text;
        }
        return '';
    };

    const out = [];
    const SKIP_TYPES = new Set(['submit', 'reset', 'button', 'image', 'hidden', 'file']);

    const inputs = document.querySelectorAll('input, select, textarea');
    inputs.forEach((el, idx) => {
        if (!isVisible(el)) return;
        if (el.disabled) return;
        const tag = el.tagName.toLowerCase();
        const type = (el.type || tag).toLowerCase();
        if (tag === 'input' && SKIP_TYPES.has(type)) return;

        let options = null;
        if (tag === 'select') {
            options = Array.from(el.options).map(o => ({
                value: o.value,
                label: (o.textContent || '').trim(),
            }));
        }

        let radioGroup = null;
        if (type === 'radio' && el.name) {
            const peers = document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`);
            // Only emit one entry per radio group — for the first peer we encounter.
            if (peers[0] !== el) return;
            radioGroup = Array.from(peers).map(r => ({
                value: r.value,
                label: labelFor(r) || r.value,
            }));
        }

        // Build a stable selector
        let selector = '';
        if (el.id) {
            selector = `#${CSS.escape(el.id)}`;
        } else if (el.name) {
            selector = `${tag}[name="${CSS.escape(el.name)}"]`;
            if (type === 'radio') {
                // group selector — caller will pick by value
                selector = `input[type="radio"][name="${CSS.escape(el.name)}"]`;
            }
        } else {
            // last resort: nth-of-type-ish
            selector = `${tag}:nth-of-type(${idx + 1})`;
        }

        out.push({
            tag,
            type,
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            label: labelFor(el),
            required: el.required || false,
            autocomplete: el.getAttribute('autocomplete') || '',
            maxlength: el.maxLength > 0 ? el.maxLength : null,
            options,
            radio_group: radioGroup,
            selector,
            checked: el.checked || false,
            multiple: el.multiple || false,
            index: idx,
        });
    });
    return out;
}
"""


@dataclass
class FieldInfo:
    tag: str
    type: str
    name: str
    id: str
    placeholder: str
    label: str
    required: bool
    autocomplete: str
    maxlength: int | None
    options: list[dict[str, str]] | None
    radio_group: list[dict[str, str]] | None
    selector: str
    checked: bool
    multiple: bool
    index: int = 0
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        """Stable hash used as the custom_answers key. Survives re-renders."""
        basis = (
            self.label.strip().lower()
            or self.name.strip().lower()
            or self.placeholder.strip().lower()
            or self.id.strip().lower()
        )
        basis = re.sub(r"\s+", " ", basis)
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def display(self) -> str:
        """Human-readable hint shown to the user when we ask about this field."""
        return (
            self.label
            or self.placeholder
            or self.name
            or self.id
            or f"{self.tag}/{self.type}"
        )


async def detect_fields(page: Page) -> list[FieldInfo]:
    raw = await page.evaluate(_COLLECT_JS)
    return [FieldInfo(**item) for item in raw]
