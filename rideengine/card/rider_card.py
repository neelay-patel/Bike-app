"""The rider card: you as a trump card (look D). The avatar, your ratings out of 99 from the last 12
months (rideengine/analysis/collection.ratings), your rider type, and how many badges you've earned.
Same size and frame as the ride cards (360 x 640), so it sits at the front of the binder.
"""
from __future__ import annotations

import html
from datetime import date

from .avatar import avatar_svg
from .ride_card import GOOGLE_FONTS, LOCAL_FONTS, _tokens

LABELS = [("distance", "Distance"), ("climbing", "Climbing"), ("speed", "Speed"), ("endurance", "Endurance"),
          ("consistency", "Consistency")]


def rider_card(ratings: dict, avatar: dict | None, name: str = "Rider", badges_earned: int = 0,
               badges_total: int = 0, year: int | None = None, fonts: str = "google",
               background: str = "#FFFFFF") -> str:
    t = _tokens()
    c, f = t["color"], t["font"]
    year = year or date.today().year
    r = ratings["ratings"]
    dots = (f'<pattern id="riderdots" width="9" height="9" patternUnits="userSpaceOnUse">'
            f'<circle cx="4.5" cy="4.5" r="1.1" fill="{c["cobaltLine"]}"/></pattern>')
    rows = "".join(
        f'<div style="display:grid;grid-template-columns:118px 1fr 44px;align-items:center;gap:10px;padding:6px 0;'
        f'{"border-bottom:1px solid " + c["sandLine"] + ";" if i < len(LABELS) - 1 else ""}">'
        f'<span style="font-family:\'{f["label"]}\',monospace;font-size:12px;letter-spacing:0.14em">{label.upper()}</span>'
        f'<span style="height:8px;border-radius:4px;background:{c["sandLine"]};overflow:hidden">'
        f'<span style="display:block;height:100%;width:{r[key]}%;background:{c["cobalt"]}"></span></span>'
        f'<span style="font-family:\'{f["hero"]}\',monospace;font-size:24px;font-weight:900;text-align:right">{r[key]}</span>'
        f'</div>'
        for i, (key, label) in enumerate(LABELS))
    stripes = "".join(f'<div style="height:4px;background:{x}"></div>' for x in c["stripes"])
    from .avatar import silhouette_svg
    portrait = (avatar_svg(avatar, size=250, title=f"{name}'s avatar", uid="rider") if avatar
                else silhouette_svg(250, color=c["cobaltSoft"]))
    from .avatar import clean
    disc = c["cobaltLine"] if not avatar or clean(avatar)["jersey"] in ("white", "sand", "yellow") else c["ground"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} · rider card</title>
{GOOGLE_FONTS if fonts == "google" else "<style>" + LOCAL_FONTS + "</style>"}
<style>body{{margin:0;background:{background};display:flex;justify-content:center}}</style></head>
<body>
<article style="width:360px;height:640px;box-sizing:border-box;background:{background};padding:12px;display:flex;flex-direction:column;color:{c['ink']}">
<header style="background:{c['strip']};color:#FFFFFF;border-radius:14px 14px 0 0;padding:10px 14px;display:flex;align-items:baseline;justify-content:space-between;gap:8px">
<h1 style="margin:0;font-family:'{f['heading']}',serif;font-size:30px;font-weight:400;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{html.escape(name)}</h1>
<span style="font-family:'{f['label']}',monospace;font-size:11px;letter-spacing:0.14em;color:#E2DADC;white-space:nowrap">RIDER · {year}</span>
</header>
<div style="position:relative;background:{c['cobalt']};height:300px;overflow:hidden">
<svg width="336" height="300" style="position:absolute;left:0;top:0" aria-hidden="true"><defs>{dots}</defs>
<rect width="336" height="300" fill="url(#riderdots)"/></svg>
<div style="position:absolute;right:-6px;bottom:-40px;width:280px;height:280px;border-radius:50%;background:{disc}"></div>
<div style="position:absolute;right:-14px;bottom:-6px">{portrait}</div>
<div style="position:absolute;left:16px;top:14px;color:#FFFFFF">
<div style="font-family:'{f['label']}',monospace;font-size:11px;letter-spacing:0.14em;color:#E3E8F7">OVERALL</div>
<div style="font-family:'{f['hero']}',monospace;font-size:78px;font-weight:900;line-height:1">{ratings['overall']}</div>
<div style="display:inline-block;margin-top:8px;padding:4px 10px;border-radius:12px;background:{c['sand']};color:{c['ink']};font-family:'{f['label']}',monospace;font-size:12px;letter-spacing:0.14em">{html.escape(ratings['type'].upper())}</div>
</div>
</div>
<div aria-hidden="true" style="display:flex;flex-direction:column">{stripes}</div>
<div style="flex:1;background:{c['sand']};border-radius:0 0 14px 14px;padding:8px 14px 10px 14px;display:flex;flex-direction:column;justify-content:space-between">
<div>{rows}</div>
<div style="display:flex;justify-content:space-between;gap:8px;white-space:nowrap;font-family:'{f['label']}',monospace;font-size:10px;letter-spacing:0.06em;color:{c['inkSoft']}">
<span>{ratings['rides']} RIDES · {ratings['km']:,} KM · 12 MONTHS</span><span>{badges_earned}/{badges_total} BADGES</span></div>
</div>
</article>
</body></html>
"""
