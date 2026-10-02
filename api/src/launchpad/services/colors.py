"""Logo colour extraction + WCAG contrast maths."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import Literal

from PIL import Image

MIN_SHARE = 0.03

Rating = Literal["AAA", "AA", "AA large", "fail"]


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def wcag_rating(ratio: float) -> Rating:
    if ratio >= 7:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3:
        return "AA large"
    return "fail"


@dataclass(frozen=True)
class PaletteColor:
    hex: str
    share: float  # fraction of counted (non-background) pixels
    role: str  # primary | secondary | accent | extra
    contrast_white: float
    contrast_black: float
    rating_on_white: Rating
    rating_on_black: Rating
    best_text: Literal["#FFFFFF", "#000000"]


def _is_background(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    hi, lo = max(rgb), min(rgb)
    near_white = lo >= 235
    near_black = hi <= 28
    # Very light greys (low saturation, high value) are usually paper/background too.
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    light_grey = v > 0.92 and s < 0.06
    return near_white or near_black or light_grey


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    # "Redmean" approximation of perceptual distance.
    rmean = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return float(
        ((2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db) ** 0.5
    )


def extract_palette(img: Image.Image, n: int = 5) -> list[PaletteColor]:
    """Up to `n` dominant colours, ignoring transparent and near-white/black pixels."""
    rgba = img.convert("RGBA")
    rgba.thumbnail((200, 200))
    # RGBA mode guarantees 4-int tuples; Pillow's stub types are wider than reality.
    pixels: list[tuple[int, int, int, int]] = list(rgba.get_flattened_data())  # type: ignore[arg-type]
    opaque = [(r, g, b) for r, g, b, a in pixels if a >= 128]
    counted = [p for p in opaque if not _is_background(p)]
    if not counted:
        return []

    sample = Image.new("RGB", (len(counted), 1))
    sample.putdata(counted)
    quant = sample.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    counts: list[tuple[int, int]] = sorted(quant.getcolors() or [], reverse=True)  # type: ignore[arg-type]

    picked: list[tuple[tuple[int, int, int], int]] = []
    for count, idx in counts:
        rgb = (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2])
        if _is_background(rgb):
            continue
        # Merge near-duplicates into the colour already picked.
        for i, (prev, prev_count) in enumerate(picked):
            if _distance(prev, rgb) < 60:
                picked[i] = (prev, prev_count + count)
                break
        else:
            picked.append((rgb, count))
    picked.sort(key=lambda p: p[1], reverse=True)
    # Drop specks (anti-aliasing blends between two real colours, stray pixels).
    counted_total = sum(c for _, c in picked) or 1
    picked = [p for p in picked if p[1] / counted_total >= MIN_SHARE][:n]

    total = sum(c for _, c in picked) or 1
    roles = _assign_roles([rgb for rgb, _ in picked])
    white, black = (255, 255, 255), (0, 0, 0)
    out = []
    for (rgb, count), role in zip(picked, roles, strict=True):
        cw, cb = contrast_ratio(rgb, white), contrast_ratio(rgb, black)
        out.append(
            PaletteColor(
                hex=rgb_to_hex(rgb),
                share=round(count / total, 3),
                role=role,
                contrast_white=cw,
                contrast_black=cb,
                rating_on_white=wcag_rating(cw),
                rating_on_black=wcag_rating(cb),
                best_text="#FFFFFF" if cw >= cb else "#000000",
            )
        )
    return out


def _assign_roles(colors: list[tuple[int, int, int]]) -> list[str]:
    """Primary = most dominant; secondary = next dominant that differs clearly;
    accent = the most saturated of the rest."""
    roles = ["extra"] * len(colors)
    if not colors:
        return roles
    roles[0] = "primary"
    rest = list(range(1, len(colors)))
    secondary = next(
        (i for i in rest if _distance(colors[i], colors[0]) >= 100), rest[0] if rest else None
    )
    if secondary is not None:
        roles[secondary] = "secondary"
        rest.remove(secondary)
    if rest:

        def saturation(i: int) -> float:
            r, g, b = colors[i]
            return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1]

        roles[max(rest, key=saturation)] = "accent"
    return roles
