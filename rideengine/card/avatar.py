"""The rider's avatar: a flat, bold head-and-shoulders drawn in code (SVG), in our own look (D).

Built from parts the rider picks (avatar builder in the app). Drawn here so it's the same everywhere:
the builder preview, the rider card, and big and quiet behind the ride card's map (mono=...).

    svg = avatar_svg({"skin": "s3", "hair": "short", "headwear": "helmet", "jersey": "cobalt", ...})
"""
from __future__ import annotations

import html

# Choices, in the order the builder shows them. Colours are named so the app can show swatches.
SKIN = {"s1": "#F5D3B8", "s2": "#E8B48F", "s3": "#C98E66", "s4": "#A0694A", "s5": "#7A4A33", "s6": "#4E2F22"}
HAIR_COLOR = {"black": "#1E1714", "brown": "#5A3A26", "auburn": "#8A4026", "blond": "#D9B26A",
              "grey": "#9C9693", "white": "#E9E4E0"}
KIT = {"cobalt": "#1D3A8C", "wine": "#7C1E3E", "ink": "#1B1618", "sand": "#F1E2B6", "sky": "#4A86E8",
       "red": "#D7263D", "green": "#3A9D4A", "yellow": "#F3C623", "white": "#FBF8F8", "orange": "#E9772E"}
OPTIONS = {
    "skin": list(SKIN),
    "face": ["oval", "round", "long"],
    "hair": ["short", "buzz", "curly", "long", "none"],
    "hair_color": list(HAIR_COLOR),
    "beard": ["none", "stubble", "short", "full", "moustache"],
    "glasses": ["none", "round", "square", "shades"],
    "headwear": ["helmet", "cap", "none"],
    "helmet_color": list(KIT),
    "jersey": list(KIT),
    "accent": list(KIT),
    "pattern": ["band", "sash", "hoops", "plain"],
    "bike": ["road", "gravel", "mtb", "indoor"],
}
DEFAULT = {"skin": "s3", "face": "oval", "hair": "short", "hair_color": "brown", "beard": "none",
           "glasses": "none", "headwear": "helmet", "helmet_color": "white", "jersey": "cobalt",
           "accent": "sand", "pattern": "band", "bike": "road"}


def clean(spec: dict | None) -> dict:
    """A complete, valid spec: unknown keys dropped, unknown values replaced by the default."""
    spec = spec or {}
    return {k: spec[k] if isinstance(spec.get(k), str) and spec[k] in OPTIONS[k] else DEFAULT[k] for k in OPTIONS}


def _shade(hex_color: str, f: float) -> str:
    """Darker (f < 1) or lighter (f > 1) version of a colour."""
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    if f < 1:
        rgb = [round(c * f) for c in rgb]
    else:
        rgb = [round(c + (255 - c) * (f - 1)) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def avatar_svg(spec: dict | None = None, size: int = 200, mono: str | None = None, title: str = "Rider avatar",
               standalone: bool = True, uid: str = "a") -> str:
    """The avatar as SVG (viewBox 200 x 240). mono: draw everything in tints of one colour (for the
    quiet background behind a ride card's map). standalone: include the <svg> wrapper."""
    s = clean(spec)
    skin = SKIN[s["skin"]]
    hair = HAIR_COLOR[s["hair_color"]]
    jersey, accent, lid = KIT[s["jersey"]], KIT[s["accent"]], KIT[s["helmet_color"]]
    ink = "#1B1618"
    if mono:  # tints of one colour, lighter = nearer
        skin, hair, jersey, accent, lid, ink = (_shade(mono, 1.35), _shade(mono, 1.12), _shade(mono, 1.2),
                                                _shade(mono, 1.45), _shade(mono, 1.55), _shade(mono, 1.05))
    skin_dark = _shade(skin, 0.86)
    rx, ry = {"oval": (40, 49), "round": (44, 45), "long": (37, 53)}[s["face"]]
    cx, cy = 100, 112
    top = cy - ry
    parts: list[str] = []
    add = parts.append

    # Long hair falls behind the shoulders, so it goes first.
    if s["hair"] == "long":
        add(f'<path d="M{cx - rx - 6} {cy - 10} Q{cx - rx - 14} {cy + 60} {cx - rx + 2} {cy + 78} L{cx + rx - 2} {cy + 78} '
            f'Q{cx + rx + 14} {cy + 60} {cx + rx + 6} {cy - 10} Z" fill="{hair}"/>')

    # Shoulders and jersey.
    body = "M18 240 C20 196 52 178 100 176 C148 178 180 196 182 240 Z"
    add(f'<path d="{body}" fill="{jersey}"/>')
    add(f'<clipPath id="kit-{uid}"><path d="{body}"/></clipPath>')
    if s["pattern"] == "band":
        add(f'<rect x="0" y="206" width="200" height="14" fill="{accent}" clip-path="url(#kit-{uid})"/>')
    elif s["pattern"] == "sash":
        add(f'<path d="M40 178 L66 178 L170 240 L140 240 Z" fill="{accent}" clip-path="url(#kit-{uid})"/>')
    elif s["pattern"] == "hoops":
        for y in (196, 214, 232):
            add(f'<rect x="0" y="{y}" width="200" height="8" fill="{accent}" clip-path="url(#kit-{uid})"/>')
    # Collar and zip.
    add(f'<path d="M82 178 Q100 192 118 178 L114 176 Q100 186 86 176 Z" fill="{_shade(jersey, 0.75)}"/>')
    add(f'<line x1="100" y1="188" x2="100" y2="240" stroke="{_shade(jersey, 0.7)}" stroke-width="2"/>')

    # Neck, ears, head.
    add(f'<path d="M86 {cy + ry - 14} L86 182 Q100 190 114 182 L114 {cy + ry - 14} Z" fill="{skin_dark}"/>')
    add(f'<ellipse cx="{cx - rx + 1}" cy="{cy + 6}" rx="7" ry="11" fill="{skin_dark}"/>')
    add(f'<ellipse cx="{cx + rx - 1}" cy="{cy + 6}" rx="7" ry="11" fill="{skin_dark}"/>')
    add(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{skin}"/>')

    # Hair on top (under any headwear).
    if s["hair"] in ("short", "curly", "long") or (s["hair"] == "buzz" and s["headwear"] == "none"):
        if s["hair"] == "curly":
            for i in range(9):
                x = cx - rx + 4 + i * (2 * rx - 8) / 8
                y = top + 12 - (12 if 2 <= i <= 6 else 2)
                add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="{hair}"/>')
        else:
            thick = 8 if s["hair"] == "buzz" else 16
            add(f'<path d="M{cx - rx} {cy - 8} Q{cx - rx} {top - 4} {cx} {top - 6} Q{cx + rx} {top - 4} {cx + rx} {cy - 8} '
                f'Q{cx + rx - 6} {top + thick} {cx + 10} {top + thick - 2} Q{cx - 18} {top + thick + 4} {cx - rx} {cy - 8} Z" '
                f'fill="{hair}"/>')

    # Beard.
    jaw = f"M{cx - rx + 4} {cy + 2} Q{cx - rx + 6} {cy + ry} {cx} {cy + ry + 2} Q{cx + rx - 6} {cy + ry} {cx + rx - 4} {cy + 2}"
    if s["beard"] == "stubble":
        add(f'<path d="{jaw} Q{cx} {cy + 26} {cx - rx + 4} {cy + 2} Z" fill="{hair}" opacity="0.28"/>')
    elif s["beard"] in ("short", "full"):
        inner = cy + 20 if s["beard"] == "short" else cy + 16
        add(f'<path d="{jaw} Q{cx + 14} {inner} {cx} {inner + 6} Q{cx - 14} {inner} {cx - rx + 4} {cy + 2} Z" fill="{hair}"/>')
    if s["beard"] in ("moustache", "short", "full"):
        add(f'<path d="M{cx - 14} {cy + 22} Q{cx} {cy + 14} {cx + 14} {cy + 22} Q{cx} {cy + 19} {cx - 14} {cy + 22} Z" '
            f'fill="{hair}" stroke="{hair}" stroke-width="3" stroke-linejoin="round"/>')

    # Face: brows, eyes, nose, smile.
    ey = cy - 2
    for dx in (-15, 15):
        add(f'<path d="M{cx + dx - 7} {ey - 10} Q{cx + dx} {ey - 14} {cx + dx + 7} {ey - 10}" fill="none" '
            f'stroke="{hair if not mono else ink}" stroke-width="3" stroke-linecap="round"/>')
        add(f'<ellipse cx="{cx + dx}" cy="{ey}" rx="3.6" ry="4.4" fill="{ink}"/>')
    add(f'<path d="M{cx + 1} {ey + 6} Q{cx + 5} {ey + 16} {cx - 2} {ey + 17}" fill="none" stroke="{skin_dark}" '
        f'stroke-width="2.5" stroke-linecap="round"/>')
    mouth = ink if s["beard"] not in ("short", "full") else _shade(hair, 1.7)
    add(f'<path d="M{cx - 9} {cy + 28} Q{cx} {cy + 34} {cx + 9} {cy + 28}" fill="none" stroke="{mouth}" '
        f'stroke-width="2.5" stroke-linecap="round"/>')

    # Glasses.
    if s["glasses"] in ("round", "square"):
        for dx in (-15, 15):
            if s["glasses"] == "round":
                add(f'<circle cx="{cx + dx}" cy="{ey}" r="10" fill="none" stroke="{ink}" stroke-width="2.5"/>')
            else:
                add(f'<rect x="{cx + dx - 11}" y="{ey - 8}" width="22" height="16" rx="3" fill="none" stroke="{ink}" stroke-width="2.5"/>')
        add(f'<line x1="{cx - 5}" y1="{ey - 1}" x2="{cx + 5}" y2="{ey - 1}" stroke="{ink}" stroke-width="2.5"/>')
    elif s["glasses"] == "shades":
        lens = _shade(accent, 0.55) if not mono else ink
        add(f'<path d="M{cx - rx + 2} {ey - 6} Q{cx} {ey - 14} {cx + rx - 2} {ey - 6} L{cx + rx - 4} {ey + 4} '
            f'Q{cx + 16} {ey + 12} {cx + 3} {ey + 4} L{cx - 3} {ey + 4} Q{cx - 16} {ey + 12} {cx - rx + 4} {ey + 4} Z" '
            f'fill="{lens}"/>')
        add(f'<path d="M{cx - 26} {ey - 4} Q{cx - 16} {ey - 8} {cx - 6} {ey - 4}" fill="none" stroke="#FFFFFF" '
            f'stroke-width="2" opacity="0.6" stroke-linecap="round"/>')

    # Headwear.
    if s["headwear"] == "helmet":
        add(f'<path d="M{cx - rx - 8} {cy - 12} Q{cx - rx - 8} {top - 22} {cx} {top - 24} Q{cx + rx + 8} {top - 22} '
            f'{cx + rx + 8} {cy - 12} Q{cx + rx} {cy - 18} {cx + rx - 6} {cy - 16} L{cx - rx + 6} {cy - 16} '
            f'Q{cx - rx} {cy - 18} {cx - rx - 8} {cy - 12} Z" fill="{lid}"/>')
        vent = _shade(lid, 0.7) if lid != KIT["ink"] else "#3A3336"
        for dx, w in ((-24, 9), (-6, 12), (14, 9)):
            add(f'<path d="M{cx + dx} {top - 14} Q{cx + dx + w / 2} {top - 19} {cx + dx + w} {top - 14} L{cx + dx + w - 1} {top + 4} '
                f'L{cx + dx + 1} {top + 4} Z" fill="{vent}"/>')
        add(f'<path d="M{cx - rx - 8} {cy - 12} Q{cx} {cy - 24} {cx + rx + 8} {cy - 12}" fill="none" stroke="{accent}" stroke-width="4"/>')
        add(f'<path d="M{cx - rx + 2} {cy - 10} L{cx - rx + 6} {cy + 30}" stroke="{ink}" stroke-width="2.5" opacity="0.8"/>')
        add(f'<path d="M{cx + rx - 2} {cy - 10} L{cx + rx - 6} {cy + 30}" stroke="{ink}" stroke-width="2.5" opacity="0.8"/>')
    elif s["headwear"] == "cap":
        add(f'<path d="M{cx - rx - 2} {cy - 16} Q{cx - rx} {top - 10} {cx} {top - 12} Q{cx + rx} {top - 10} {cx + rx + 2} {cy - 16} Z" '
            f'fill="{lid}"/>')
        add(f'<rect x="{cx - 6}" y="{top - 11}" width="12" height="{cy - 16 - top + 11}" fill="{accent}"/>')
        add(f'<path d="M{cx - 30} {cy - 16} Q{cx} {cy - 30} {cx + 30} {cy - 16} L{cx + 26} {cy - 24} Q{cx} {cy - 36} '
            f'{cx - 26} {cy - 24} Z" fill="{_shade(lid, 0.8)}"/>')

    inner = "".join(parts)
    if not standalone:
        return inner
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 240" width="{size}" height="{round(size * 1.2)}" '
            f'role="img" aria-label="{html.escape(title)}">{inner}</svg>')
