import colorsys
import io
import logging
import math

from PIL import Image

from sources.coverart import cover_url, fetch_cover
from sources.http import SourceUnavailable

logger = logging.getLogger(__name__)

DEFAULT_ACCENT = "#c8a45a"
BACKGROUND = "#141210"


def _rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(max(0.0, min(1.0, c)) * 255) for c in (r, g, b)))


def _luminance(color: str) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(color: str, background: str = BACKGROUND, minimum: float = 3.0) -> str:
    h, l, s = colorsys.rgb_to_hls(*_rgb(color))
    out = color
    while contrast_ratio(out, background) < minimum and l < 1.0:
        l = min(1.0, l + 0.05)
        out = _hex(*colorsys.hls_to_rgb(h, l, s))
    return out


def extract_accent(image: bytes) -> str:
    img = Image.open(io.BytesIO(image)).convert("RGB").resize((64, 64))
    quantized = img.quantize(8)
    palette = quantized.getpalette()
    best, best_score = None, 0.0
    for count, index in quantized.getcolors():
        r, g, b = (palette[index * 3 + i] / 255 for i in range(3))
        _, l, s = colorsys.rgb_to_hls(r, g, b)
        if s < 0.25 or l < 0.12 or l > 0.92:
            continue
        score = s * math.sqrt(count)
        if score > best_score:
            best, best_score = _hex(r, g, b), score
    if best is None:
        return DEFAULT_ACCENT
    return ensure_contrast(best)


def apply_cover_and_accent(album) -> None:
    """Enricher: set cover_url (only when a cover exists) and accent_color, respecting locks."""
    try:
        data = fetch_cover(str(album.mbid))
    except SourceUnavailable:
        logger.warning("cover for %r unavailable (Cover Art Archive down); continuing without it", album)
        return
    if data is None:
        return
    values = {"cover_url": cover_url(str(album.mbid))}
    try:
        values["accent_color"] = extract_accent(data)
    except (OSError, ValueError):
        pass  # unreadable image: keep the cover, leave the default accent
    changed = album.apply_source_fields(**values)
    if changed:
        album.save(update_fields=changed)
