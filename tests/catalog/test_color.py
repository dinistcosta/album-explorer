import colorsys
import io

import pytest
from PIL import Image

from catalog.services.color import (
    BACKGROUND, DEFAULT_ACCENT, contrast_ratio, ensure_contrast, extract_accent,
)


def solid_png(color, size=100, patches=()):
    img = Image.new("RGB", (size, size), color)
    for box, c in patches:
        img.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), c), box[:2])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def hue(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def test_contrast_ratio_black_white():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, rel=1e-3)


def test_dark_colour_is_lightened():
    out = ensure_contrast("#1d1a40")
    assert contrast_ratio(out, BACKGROUND) >= 3.0


def test_bright_colour_unchanged():
    assert ensure_contrast("#c8a45a") == "#c8a45a"


def test_extract_accent_picks_saturated_blue():
    img = solid_png("#2f7cc0", 100, patches=[((0, 0, 40, 100), "#808080")])
    out = extract_accent(img)
    assert abs(hue(out) - hue("#2f7cc0")) <= 10
    assert contrast_ratio(out, BACKGROUND) >= 3.0


def test_greyscale_cover_uses_default():
    assert extract_accent(solid_png("#808080")) == DEFAULT_ACCENT
