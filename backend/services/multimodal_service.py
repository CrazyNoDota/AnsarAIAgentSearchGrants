"""
Phase 3 — Multimodal grant-call / document reader (NVIDIA NIM · StepFun).

Uses `stepfun-ai/step-3.7-flash` (vision-capable) to OCR-read scanned or
PDF grant calls and user-supplied documents, returning their text/structured
content so the document generator can ground drafts in the real call text.

The model is called via the OpenAI-compatible Chat Completions API with
`image_url` content parts carrying base64 **data-URLs** (png/jpg/jpeg/webp), as
documented for step-3.7-flash. PDFs are rasterized page-by-page to PNG with
PyMuPDF (optional dependency — imported lazily so the rest of the backend works
without it).
"""
from __future__ import annotations

import base64
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MULTIMODAL_TIMEOUT_SECONDS = 90
# Cap pages sent per request to keep latency/cost and the request size bounded.
MAX_PDF_PAGES = 8
# Render scale for PDF→image (1.0 ≈ 72dpi). 2.0 gives ~144dpi — enough for OCR.
PDF_RENDER_ZOOM = 2.0
# Hard cap on the rendered pixel dimension of a single page. A small PDF can
# declare huge page dimensions; without this a single get_pixmap() could try to
# allocate an enormous bitmap. Zoom is reduced per page to honour this bound.
MAX_RENDER_DIM_PX = 2200

DEFAULT_INSTRUCTION = (
    "You are reading a grant call / funding document. Transcribe and summarise "
    "the key information as plain text: program name, funder, eligibility, "
    "funding amount/range, deadlines, required application sections and any "
    "evaluation criteria. Transcribe figures and dates exactly as shown. Do not "
    "invent details that are not visible in the document."
)

_SUPPORTED_IMAGE_MIME = {
    "image/png", "image/jpeg", "image/jpg", "image/webp",
}


def image_bytes_to_data_url(data: bytes, mime: str = "image/png") -> str:
    """Encode raw image bytes as an OpenAI-compatible base64 data-URL."""
    if mime not in _SUPPORTED_IMAGE_MIME:
        raise ValueError(
            f"Unsupported image mime '{mime}'. Supported: "
            f"{', '.join(sorted(_SUPPORTED_IMAGE_MIME))}"
        )
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def pdf_bytes_to_image_data_urls(
    pdf_bytes: bytes, max_pages: int = MAX_PDF_PAGES
) -> list[str]:
    """Rasterize the first ``max_pages`` PDF pages to PNG data-URLs.

    Requires PyMuPDF (``pymupdf`` / import name ``fitz``). Imported lazily and
    raised as a clear RuntimeError when missing so the dependency is optional.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "PDF reading requires PyMuPDF. Install it with `pip install pymupdf`."
        ) from e

    # A corrupt/non-PDF upload must surface as a ValueError (→ HTTP 400), not an
    # opaque library error (→ 500) or a RuntimeError (reserved for "dep missing").
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Could not read the uploaded PDF: {e}") from e

    data_urls: list[str] = []
    try:
        for page in doc[:max_pages]:
            # Clamp zoom so neither rendered side exceeds MAX_RENDER_DIM_PX,
            # bounding the bitmap allocation regardless of declared page size.
            # NB: never raise the zoom back up with a lower floor — for a page
            # with a huge MediaBox the safe zoom is < the floor, and flooring it
            # would defeat the cap and re-introduce a large allocation.
            rect = page.rect
            zoom = PDF_RENDER_ZOOM
            if rect.width > 0:
                zoom = min(zoom, MAX_RENDER_DIM_PX / rect.width)
            if rect.height > 0:
                zoom = min(zoom, MAX_RENDER_DIM_PX / rect.height)
            if zoom <= 0:
                # Degenerate page box (zero/negative dims) — nothing to render.
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            data_urls.append(image_bytes_to_data_url(pix.tobytes("png"), "image/png"))
    except Exception as e:
        raise ValueError(f"Failed to rasterize the uploaded PDF: {e}") from e
    finally:
        doc.close()
    return data_urls


class MultimodalService:
    """Reads images / PDFs with the StepFun multimodal model."""

    def __init__(self) -> None:
        self._client: Optional["AsyncOpenAI"] = None
        api_key = settings.step_api_key
        if api_key:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=settings.nvidia_step_base_url,
                api_key=api_key,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    @staticmethod
    def build_messages(image_data_urls: list[str], instruction: str) -> list[dict]:
        """Build the vision chat messages (pure / testable).

        One user message whose content is the instruction text followed by one
        ``image_url`` part per page/image.
        """
        content: list[dict] = [{"type": "text", "text": instruction}]
        for url in image_data_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        return [{"role": "user", "content": content}]

    async def extract_from_images(
        self,
        image_data_urls: list[str],
        instruction: str = DEFAULT_INSTRUCTION,
    ) -> Optional[str]:
        """Run the multimodal model over already-encoded image data-URLs."""
        if not self._client:
            logger.info("StepFun multimodal model not configured — skipping OCR.")
            return None
        if not image_data_urls:
            return None
        try:
            resp = await self._client.chat.completions.create(
                model=settings.nvidia_step_model,
                messages=self.build_messages(image_data_urls, instruction),
                temperature=0.0,
                max_tokens=4000,
                timeout=MULTIMODAL_TIMEOUT_SECONDS,
            )
            return (resp.choices[0].message.content or "").strip() or None
        except Exception as e:
            logger.error("multimodal extraction failed: %s", e)
            return None

    async def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        instruction: str = DEFAULT_INSTRUCTION,
        max_pages: int = MAX_PDF_PAGES,
    ) -> Optional[str]:
        """Rasterize a PDF and OCR-read it. Returns None if unavailable/empty."""
        if not self._client:
            return None
        data_urls = pdf_bytes_to_image_data_urls(pdf_bytes, max_pages=max_pages)
        return await self.extract_from_images(data_urls, instruction)

    async def extract_from_upload(
        self,
        data: bytes,
        content_type: str,
        instruction: str = DEFAULT_INSTRUCTION,
    ) -> tuple[Optional[str], int]:
        """Dispatch an uploaded file (PDF or image) to the right reader.

        Returns ``(text, n_pages_or_images)`` where ``n`` is the actual number of
        pages/images sent to the model (so the API can report it accurately).
        Raises ValueError for an unsupported or unreadable file.
        """
        ctype = (content_type or "").lower()
        if ctype == "application/pdf":
            data_urls = pdf_bytes_to_image_data_urls(data)
        elif ctype in _SUPPORTED_IMAGE_MIME:
            data_urls = [image_bytes_to_data_url(data, ctype)]
        else:
            raise ValueError(
                f"Unsupported upload type '{content_type}'. Provide a PDF or a "
                f"png/jpeg/webp image."
            )
        text = await self.extract_from_images(data_urls, instruction)
        return text, len(data_urls)
