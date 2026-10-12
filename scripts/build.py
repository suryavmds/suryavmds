#!/usr/bin/env python3
"""Draws the SVGs in assets/ from data/profile.json.

    python3 scripts/build.py            # refresh the live numbers, then draw
    python3 scripts/build.py --offline  # draw from the numbers already saved

The words on the page live in data/profile.json; edit them there. The live
numbers (contributions, the Strays release, the repo timeline) come from the
GitHub API and are saved back into the same file under "live".

Set GH_TOKEN to a token. A personal token lets the timeline count private
repos too; the token GitHub Actions provides only sees public data, so with
that one the saved repo list is left as it is.
"""
import argparse
import datetime as dt
import html
import json
import math
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "profile.json"
OUT = ROOT / "assets"

W = 840
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

# Colours follow the Strays dashboard, in its dark and light appearance.
THEMES = {
    "dark": {
        "win": "#242426", "side": "#2d2d30", "card": "#2b2d34", "edge": "#3a3c44",
        "sel": "#3f3f44", "frame": "#3d3d42", "grid": "#34353b",
        "ink": "#f2f2f4", "ink2": "#a3a3aa", "ink3": "#7c7c85",
        "blue": "#5a96ff", "blue_bg": "#2a3854", "tile": "#2e3c5a",
        "orange": "#f08c64", "orange_bg": "#3b2d28",
        "green": "#4fd675", "amber": "#f5b23d", "tag": "#3a3b42", "idle": "#6a6a72",
    },
    "light": {
        "win": "#f5f5f7", "side": "#e9e9ec", "card": "#ffffff", "edge": "#dcdce1",
        "sel": "#d8d8de", "frame": "#d0d0d6", "grid": "#e2e2e7",
        "ink": "#1d1d1f", "ink2": "#5f5f67", "ink3": "#777780",
        "blue": "#1f6feb", "blue_bg": "#e0eafd", "tile": "#dde8fc",
        "orange": "#b84a20", "orange_bg": "#fbeae3",
        "green": "#178f49", "amber": "#a86a12", "tag": "#ececf0", "idle": "#a5a5ad",
    },
}


# ---------------------------------------------------------------- live data

def api(path, token, query=None):
    url = "https://api.github.com" + path
    body = None
    if query is not None:
        body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "profile-build"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def attempt(what, fn):
    try:
        fn()
    except Exception as err:  # keep the saved value and carry on
        print("kept saved %s (%s)" % (what, err), file=sys.stderr)


def refresh(data, token):
    live, login = data["live"], data["login"]
    live["as_of"] = dt.date.today().isoformat()

    def account():
        live["created"] = api("/users/" + login, token)["created_at"][:10]

    def release():
        rel = api("/repos/%s/strays/releases/latest" % login, token)
        first = api("/repos/%s/strays/releases?per_page=100" % login, token)[-1]
        live["strays_tag"] = rel["tag_name"]
        live["strays_released"] = first["published_at"][:10]

    def contributions():
        q = ('{user(login:"%s"){contributionsCollection{contributionCalendar{'
             'totalContributions weeks{contributionDays{contributionCount}}}}}}' % login)
        cal = api("/graphql", token, q)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        live["contributions"] = cal["totalContributions"]
        live["weeks"] = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cal["weeks"]]

    def repos():
        if api("/user", token)["login"] != login:
            return
        lane_of = {lang: lane["name"] for lane in data["lanes"] for lang in lane["languages"]}
        found, page = [], 1
        while True:
            batch = api("/user/repos?affiliation=owner&per_page=100&page=%d" % page, token)
            if not batch:
                break
            for r in batch:
                if not r["fork"] and r["language"] in lane_of:
                    found.append([lane_of[r["language"]], r["created_at"][:10], r["pushed_at"][:10]])
            page += 1
        if found:
            live["repos"] = sorted(found, key=lambda r: (r[1], r[0]))

    attempt("account date", account)
    attempt("Strays release", release)
    if token:
        attempt("contributions", contributions)
        attempt("repo list", repos)


def pretty(v, depth=0):
    """JSON with short lists and objects kept on one line, so the file stays editable by hand."""
    flat = json.dumps(v, ensure_ascii=False)
    if not isinstance(v, (list, dict)) or not v or len(flat) + depth * 2 <= 110 or (
            isinstance(v, list) and not any(isinstance(i, (list, dict)) for i in v)):
        return flat
    pad, end = "  " * (depth + 1), "  " * depth
    if isinstance(v, list):
        return "[\n" + ",\n".join(pad + pretty(i, depth + 1) for i in v) + "\n" + end + "]"
    return "{\n" + ",\n".join(pad + json.dumps(k) + ": " + pretty(i, depth + 1) for k, i in v.items()) + "\n" + end + "}"


# ------------------------------------------------------------- svg helpers

def esc(s):
    return html.escape(str(s), quote=True)


def day(s):
    return dt.date.fromisoformat(s)


def width_of(s, size, bold=False):
    """Rough rendered width of sans text; only used to size pills."""
    total = 0.0
    for ch in s:
        if ch in "iljtf.,:;'|! ":
            total += 0.30
        elif ch in "mwMW@":
            total += 0.86
        elif ch.isupper():
            total += 0.67
        elif ch.isdigit():
            total += 0.60
        else:
            total += 0.54
    return total * size * (1.05 if bold else 1.0)


def text(x, y, s, size=13, weight=400, fill="ink", anchor=None, mono=False, extra=""):
    cls = ("m " if mono else "") + fill
    anc = ' text-anchor="%s"' % anchor if anchor else ""
    return '<text x="%s" y="%s" font-size="%s" font-weight="%s" class="%s"%s%s>%s</text>' % (
        x, y, size, weight, cls, anc, extra, esc(s))


def css(t):
    return (
        "text{font-family:%s}.m{font-family:%s}" % (SANS, MONO)
        + ".ink{fill:%(ink)s}.ink2{fill:%(ink2)s}.ink3{fill:%(ink3)s}"
          ".blue{fill:%(blue)s}.orange{fill:%(orange)s}" % t
        + "@keyframes pulse{0%{transform:scale(1);opacity:.6}75%,100%{transform:scale(2.8);opacity:0}}"
          ".pulse{transform-box:fill-box;transform-origin:center;animation:pulse 2.6s ease-out infinite}"
          "@keyframes scroll{to{transform:translateX(-96px)}}"
          ".beat{animation:scroll 5s linear infinite}"
          "@keyframes pick{0%{opacity:1}33.3%,100%{opacity:0}}"
          ".pick{animation:pick 12s step-end infinite}"
          "@keyframes type{0%,60%,100%{opacity:.35}30%{opacity:1}}"
          ".type{animation:type 1.4s ease-in-out infinite}"
          "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    )


def svg(w, h, label, body, t):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img" aria-label="%s">\n<title>%s</title>\n<style>%s</style>\n%s\n</svg>\n'
        % (w, h, w, h, esc(label), esc(label), css(t), body)
    )


def panel(w, h, t):
    return '<rect x=".5" y=".5" width="%s" height="%s" rx="14" fill="%s" stroke="%s"/>' % (
        w - 1, h - 1, t["win"], t["frame"])


def card(x, y, w, h, t):
    return '<rect x="%s" y="%s" width="%s" height="%s" rx="12" fill="%s" stroke="%s"/>' % (
        x, y, w, h, t["card"], t["edge"])


def icon(name, x, y, c, bg=None):
    """16px line icons for the sidebar and section headers."""
    s = 'fill="none" stroke="%s" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"' % c
    shapes = {
        "grid": '<g %s><rect x="1.7" y="1.7" width="5" height="5" rx="1.3"/><rect x="9.3" y="1.7" width="5" height="5" rx="1.3"/>'
                '<rect x="1.7" y="9.3" width="5" height="5" rx="1.3"/><rect x="9.3" y="9.3" width="5" height="5" rx="1.3"/></g>' % s,
        "ports": '<g %s><circle cx="3.2" cy="3.6" r="1.7"/><circle cx="12.8" cy="3.6" r="1.7"/><circle cx="8" cy="12.6" r="1.7"/>'
                 '<path d="M3.2 5.3v1.2c0 .9.7 1.6 1.6 1.6h6.4c.9 0 1.6-.7 1.6-1.6V5.3M8 8.1v2.8"/></g>' % s,
        "folder": '<path %s d="M1.6 4.3c0-.7.5-1.2 1.2-1.2h3l1.4 1.5h6c.7 0 1.2.5 1.2 1.2v6c0 .7-.5 1.2-1.2 1.2H2.8c-.7 0-1.2-.5-1.2-1.2z"/>' % s,
        "cap": '<g %s><path d="M1.2 6.2 8 3l6.8 3.2L8 9.4z"/><path d="M4.1 7.8v2.8c0 .9 1.7 1.8 3.9 1.8s3.9-.9 3.9-1.8V7.8"/></g>' % s,
        "layers": '<g %s><path d="M8 2 14.4 5.1 8 8.2 1.6 5.1z"/><path d="M1.6 8 8 11.1 14.4 8M1.6 10.9 8 14l6.4-3.1"/></g>' % s,
        "bars": '<g fill="%s"><rect x="2" y="8" width="3" height="6" rx="1"/><rect x="6.5" y="3" width="3" height="11" rx="1"/>'
                '<rect x="11" y="6" width="3" height="8" rx="1"/></g>' % c,
        "warn": '<path d="M8 1.6c.5 0 .9.3 1.2.7l5.5 9.6c.5.9-.1 2.1-1.2 2.1h-11c-1.1 0-1.7-1.2-1.2-2.1l5.5-9.6c.3-.4.7-.7 1.2-.7z" fill="%s"/>'
                '<rect x="7.25" y="5.2" width="1.5" height="4.6" rx=".75" fill="%s"/><circle cx="8" cy="11.7" r=".9" fill="%s"/>' % (c, bg, bg),
    }
    return '<g transform="translate(%s %s)">%s</g>' % (x, y, shapes[name])


def tile(name, x, y, t, size=40):
    """The rounded icon tile at the top left of every card."""
    c = t["blue"]
    s = 'fill="none" stroke="%s" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"' % c
    glyphs = {
        "chat": '<path %s d="M5.5 4.5h13a2.5 2.5 0 0 1 2.5 2.5v7.5a2.5 2.5 0 0 1-2.5 2.5h-6.2L8 20.6V17H5.500a2.5 2.5 0 0 1-2.5-2.5V7a2.5 2.5 0 0 1 2.5-2.5z"/>' % s
                + "".join('<circle class="type" style="animation-delay:%ss" cx="%s" cy="10.8" r="1.15" fill="%s"/>' % (i * 0.18, 8.4 + i * 3.6, c)
                          for i in range(3)),
        "paw": '<g fill="%s"><ellipse cx="5.9" cy="9.9" rx="2" ry="2.6" transform="rotate(-22 5.9 9.9)"/>'
               '<ellipse cx="9.7" cy="6" rx="2.1" ry="2.8" transform="rotate(-7 9.7 6)"/>'
               '<ellipse cx="14.3" cy="6" rx="2.1" ry="2.8" transform="rotate(7 14.3 6)"/>'
               '<ellipse cx="18.1" cy="9.9" rx="2" ry="2.6" transform="rotate(22 18.1 9.9)"/>'
               '<path d="M12 11.3c-3.1 0-5.8 3-5.8 5.6 0 1.800 1.3 2.800 2.900 2.800 1.2 0 1.9-.6 2.9-.6s1.700.6 2.900.6c1.600 0 2.900-1 2.900-2.800 0-2.600-2.700-5.600-5.800-5.600z"/></g>' % c,
        "calc": '<g %s><rect x="5.5" y="3" width="13" height="18" rx="2.6"/><rect x="8.300" y="5.900" width="7.400" height="3.400" rx=".9"/></g>' % s
                + "".join('<circle cx="%s" cy="%s" r="1" fill="%s"/>' % (8.9 + i * 3.1, 12.9 + j * 3.3, c)
                          for i in range(3) for j in range(2)),
        "layers": '<g %s><path d="M12 3.500 20.500 7.700 12 11.900 3.500 7.700z" fill="%s"/><path d="M3.500 12 12 16.200 20.500 12M3.500 16.300 12 20.500l8.500-4.200"/></g>' % (s, c),
    }
    pad = (size - 24) / 2.0
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s"/><g transform="translate(%s %s)">%s</g>'
            % (x, y, size, size, size / 4.0, t["tile"], x + pad, y + pad, glyphs[name]))


def pill(x, y, label, kind, t):
    """Returns (svg, width). kind: port | tag | orphan."""
    h = 22
    if kind == "port":
        w = round(len(label) * 7.4 + 18)
        return ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s"/>' % (x, y, w, h, t["blue_bg"])
                + text(x + w / 2.0, y + 15.4, label, 12, 600, "blue", "middle", mono=True)), w
    if kind == "orphan":
        w = round(width_of(label, 12, True) + 40)
        return ('<rect x="%s" y="%s" width="%s" height="%s" rx="11" fill="%s" stroke="%s" stroke-width="1.2"/>' % (
                    x + .6, y + .6, w - 1.2, h - 1.2, t["orange_bg"], t["orange"])
                + '<g transform="translate(%s %s) scale(.78)">%s</g>' % (x + 9, y + 4.6, icon("warn", 0, 0, t["orange"], t["orange_bg"]))
                + text(x + 27, y + 15.4, label, 12, 600, "orange")), w
    w = round(width_of(label, 11.5) + 18)
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s"/>' % (x, y, w, h, t["tag"])
            + text(x + w / 2.0, y + 15.2, label, 11.5, 500, "ink2", "middle")), w


def heartbeat(x, y, color, flat=False, shift=0.0, uid="a"):
    """A sparkline that scrolls forever: three copies of one 96px period."""
    period, h, pts = 96, 18, []
    for i in range(0, period * 3 + 1, 2):
        p = (i % period) / float(period)
        if flat:
            v = 0.5 * math.exp(-((p - 0.62) / 0.018) ** 2)
        else:
            v = (0.20 * math.sin(2 * math.pi * (p + shift)) + 0.10 * math.sin(6 * math.pi * (p + shift) + 1.3)
                 + 0.95 * math.exp(-((p - 0.70) / 0.022) ** 2) - 0.30 * math.exp(-((p - 0.76) / 0.03) ** 2))
        base = h - 4 if flat else h * 0.62
        pts.append("%s,%.1f" % (i, base - v * h * 0.62))
    return (
        '<clipPath id="hb%s"><rect width="%d" height="%d"/></clipPath>'
        '<g transform="translate(%s %s)" clip-path="url(#hb%s)">'
        '<polyline class="beat" style="animation-duration:%ss" points="%s" fill="none" stroke="%s" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/></g>'
        % (uid, period, h + 2, x, y, uid, 9 if flat else 5, " ".join(pts), color)
    )


def uptime(since, as_of):
    """('4y 3mo', 'up') once something has been running a week; ('new', 'this week') before."""
    days = (as_of - since).days
    months = (as_of.year - since.year) * 12 + as_of.month - since.month - (1 if as_of.day < since.day else 0)
    if months >= 24:
        y, m = divmod(months, 12)
        return ("%dy %dmo" % (y, m) if m else "%dy" % y), "up"
    if months >= 2:
        return "%dmo" % months, "up"
    if days >= 7:
        return "%dw" % (days // 7), "up"
    return "new", "this week"


# ----------------------------------------------------------------- drawings

def hero(data, t):
    live, H = data["live"], 448
    as_of = day(live["as_of"])
    fill_in = lambda s: s.replace("{strays_tag}", live["strays_tag"]).replace("{strays_released}", live["strays_released"])
    o = [panel(W, H, t)]

    # sidebar
    o.append('<rect x="8" y="8" width="190" height="%d" rx="10" fill="%s"/>' % (H - 16, t["side"]))
    for cx, c in ((28, "#ff5f57"), (48, "#febc2e"), (68, "#28c840")):
        o.append('<circle cx="%d" cy="30" r="6" fill="%s"/>' % (cx, c))
    y = 76
    for row in data["sidebar"]:
        if row[0] == "label":
            y += 6
            o.append(text(24, y, row[1], 11, 600, "ink3"))
            y += 24
            continue
        _, ic, label, count, selected = row
        if selected:
            o.append('<rect x="14" y="%d" width="178" height="30" rx="7" fill="%s"/>' % (y - 20, t["sel"]))
        o.append(icon(ic, 24, y - 13, t["blue"]))
        o.append(text(48, y, label, 13, 500 if selected else 400, "ink"))
        if count.startswith("!"):
            o.append('<g transform="translate(160 %s) scale(.8)">%s</g>' % (y - 11, icon("warn", 0, 0, t["amber"], t["side"])))
            count = count[1:]
        o.append(text(184, y, count, 11.5, 600, "ink2", "end", mono=True))
        y += 30
    o.append('<circle class="pulse" cx="27" cy="%d" r="4" fill="%s"/><circle cx="27" cy="%d" r="4" fill="%s"/>' % (
        H - 28, t["green"], H - 28, t["green"]))
    o.append(text(40, H - 24, "Live data", 11.5, 500, "ink2"))

    # header: name on the left, a year of contributions on the right
    x0, x1 = 222, 816
    years = as_of.year - day(live["created"]).year - (1 if (as_of.month, as_of.day) < (day(live["created"]).month, day(live["created"]).day) else 0)
    o.append(text(x0, 46, data["name"], 25, 700, "ink"))
    o.append(text(x0, 68, data["tagline"], 13, 400, "ink2"))
    tx, ty, tw, th = 580, 16, x1 - 580, 68
    o.append('<rect x="%s" y="%s" width="%s" height="%s" rx="10" fill="%s" stroke="%s"/>' % (tx, ty, tw, th, t["card"], t["edge"]))
    o.append(text(tx + 12, ty + 19, "CONTRIBUTIONS, PAST YEAR", 9.5, 600, "ink3", extra=' letter-spacing=".5"'))
    o.append(text(tx + tw - 12, ty + 19.5, "{:,}".format(live["contributions"]), 13, 700, "ink", "end", mono=True))
    weeks = live["weeks"]
    px0, px1, py0, py1 = tx + 12, tx + tw - 14, ty + 31, ty + th - 10
    top = float(max(weeks) or 1)
    pts = [(px0 + (px1 - px0) * i / float(len(weeks) - 1), py1 - (py1 - py0) * v / top) for i, v in enumerate(weeks)]
    line = " ".join("%.1f,%.1f" % p for p in pts)
    o.append('<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s" stop-opacity=".32"/>'
             '<stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient></defs>' % (t["blue"], t["blue"]))
    o.append('<polygon points="%s %.1f,%.1f %.1f,%.1f" fill="url(#area)"/>' % (line, px1, py1, px0, py1))
    o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>' % (line, t["blue"]))
    o.append('<circle class="pulse" cx="%.1f" cy="%.1f" r="2.8" fill="%s"/>' % (pts[-1][0], pts[-1][1], t["blue"]))
    o.append('<circle cx="%.1f" cy="%.1f" r="2.8" fill="%s" stroke="%s" stroke-width="1.5"/>' % (pts[-1][0], pts[-1][1], t["blue"], t["card"]))

    # running
    o.append('<circle cx="%d" cy="107" r="4" fill="%s"/>' % (x0 + 6, t["green"]))
    o.append(text(x0 + 18, 111.5, "Running", 13.5, 600, "ink"))
    o.append(text(x0 + 18 + width_of("Running", 13.5, True) + 8, 111.5, str(len(data["running"])), 12.5, 500, "ink3"))
    cw, ch, cy = 289, 172, 126
    rings = []
    for i, p in enumerate(data["running"]):
        cx = x0 + i * (cw + 16)
        g = [card(cx, cy, cw, ch, t), tile(p["icon"], cx + 16, cy + 16, t)]
        g.append(text(cx + 68, cy + 33, p["title"], 16, 650, "ink"))
        g.append(text(cx + 68, cy + 51, p["sub"], 12.5, 400, "ink2"))
        px = cx + 16
        for label, kind in p["pills"]:
            s, w = pill(px, cy + 68, fill_in(label), kind, t)
            g.append(s)
            px += w + 6
        for n, ln in enumerate(p["lines"]):
            g.append(text(cx + 16, cy + 111 + n * 17, ln, 12.5, 400, "ink2"))
        g.append(heartbeat(cx + 16, cy + 140, t["blue"], shift=i * 0.37, uid=str(i)))
        big, small = uptime(day(fill_in(p["since"])), as_of)
        sw = width_of(small, 11.5)
        g.append(text(cx + cw - 16, cy + 155, small, 11.5, 400, "ink3", "end"))
        g.append(text(cx + cw - 16 - sw - 6, cy + 155, big, 12.5, 700, "ink", "end", mono=True))
        o.append("".join(g))
        rings.append((cx, cy, cw, ch))

    # orphaned
    oy = 338
    o.append(icon("warn", x0, oy - 28, t["amber"], t["win"]))
    head = "Orphaned: their session has exited"
    o.append(text(x0 + 22, oy - 15.5, head, 13.5, 600, "ink"))
    o.append(text(x0 + 22 + width_of(head, 13.5, True) + 8, oy - 15.5, "1", 12.5, 500, "ink3"))
    orphan, ow, oh = data["orphan"], x1 - x0, 84
    g = [card(x0, oy, ow, oh, t), tile("calc", x0 + 16, oy + 22, t)]
    g.append(text(x0 + 68, oy + 39, orphan["title"], 16, 650, "ink"))
    g.append(text(x0 + 68, oy + 57, orphan["sub"], 12.5, 400, "ink2"))
    s, w = pill(0, 0, orphan["pill"], "orphan", t)
    g.append('<g transform="translate(%s %s)">%s</g>' % (x1 - 16 - w, oy + 16, s))
    g.append(text(x1 - 16, oy + 64, orphan["note"], 12, 400, "ink3", "end"))
    g.append(heartbeat(x1 - 16 - width_of(orphan["note"], 12) - 14 - 96, oy + 48, t["idle"], flat=True, uid="o"))
    o.append("".join(g))
    rings.append((x0, oy, ow, oh))

    # the selection ring walks from card to card, as if someone is arrowing through
    for i, (rx, ry, rw, rh) in enumerate(rings):
        o.append('<rect class="pick" style="animation-delay:-%ds" opacity="%d" x="%s" y="%s" width="%s" height="%s" rx="12" '
                 'fill="none" stroke="%s" stroke-width="2"/>' % ((len(rings) - i) % len(rings) * 4, 1 if i == 0 else 0,
                                                              rx, ry, rw, rh, t["blue"]))

    label = "%s, drawn as the Strays dashboard. Running: %s. Orphaned from college: %s. %s contributions in the past year, %d years on GitHub." % (
        data["name"], " and ".join(p["title"] for p in data["running"]), orphan["title"], "{:,}".format(live["contributions"]), years)
    return svg(W, H, label, "\n".join(o), t)


def timeline(data, t):
    live = data["live"]
    as_of = day(live["as_of"])
    lanes = [l["name"] for l in data["lanes"]]
    repos = [(r[0], day(r[1]), day(r[2])) for r in live["repos"] if r[0] in lanes]
    first = {n: min(r[1] for r in repos if r[0] == n) for n in lanes if any(r[0] == n for r in repos)}
    lanes = sorted(first, key=first.get)
    lane_h, top = 34, 96
    H = top + len(lanes) * lane_h + 52
    X0, X1 = 152, 676
    e = min(first.values())
    t0 = dt.date(e.year, 1 if e.month <= 6 else 7, 1)
    t1 = dt.date(as_of.year + 1, 1, 1)
    xs = lambda d: X0 + (d - t0).days / float((t1 - t0).days) * (X1 - X0)

    o = [panel(W, H, t)]
    o.append(text(24, 40, "Timeline", 17, 650, "ink"))
    o.append(text(24, 61, "Every repo as a process: it starts when the repo is created and exits at the last push. %d repos, public and private." % len(repos),
                  12.5, 400, "ink2"))
    bottom = top + len(lanes) * lane_h
    for yr in range(t0.year + 1, t1.year):
        gx = xs(dt.date(yr, 1, 1))
        o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s"/>' % (gx, top - 4, gx, bottom + 4, t["grid"]))
        o.append(text("%.1f" % gx, bottom + 24, str(yr), 11.5, 400, "ink3", "middle", mono=True))
    nx = xs(as_of)
    o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-dasharray="2 3"/>' % (nx, top - 4, nx, bottom + 4, t["ink3"]))
    o.append(text("%.1f" % nx, bottom + 24, "now", 11.5, 600, "ink2", "middle"))

    for i, name in enumerate(lanes):
        cy = top + i * lane_h + lane_h / 2.0
        mine = [r for r in repos if r[0] == name]
        last = max(r[2] for r in mine)
        running = (as_of - last).days <= 90
        o.append(text(24, cy + 4.5, name, 13, 600, "ink"))
        o.append(text(136, cy + 4.5, str(len(mine)), 11.5, 500, "ink3", "end", mono=True))
        o.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>' % (X0, cy, X1, cy, t["grid"]))
        for _, a, b in sorted(mine, key=lambda r: r[1]):
            alive = (as_of - b).days <= 90
            x, w = xs(a), max(6.0, xs(b) - xs(a))
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="14" rx="4" fill="%s" opacity="%s"/>' % (
                x, cy - 7, w, t["blue"] if running else t["idle"], 1 if alive else (0.5 if running else 0.6)))
            if alive:
                o.append('<circle class="pulse" cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (x + w - 3, cy, t["blue"]))
        if running:
            o.append('<circle cx="700" cy="%.1f" r="4" fill="%s"/>' % (cy, t["green"]))
            o.append(text(712, cy + 4.5, "running", 12.5, 600, "ink"))
        else:
            o.append('<circle cx="700" cy="%.1f" r="3.4" fill="none" stroke="%s" stroke-width="1.3"/>' % (cy, t["ink3"]))
            o.append(text(712, cy + 4.5, "exited %d" % last.year, 12.5, 400, "ink2"))

    label = "Timeline of %d repos by language, %d to %d. %s." % (
        len(repos), t0.year, as_of.year,
        "; ".join("%s %s" % (n, "still running" if (as_of - max(r[2] for r in repos if r[0] == n)).days <= 90
                             else "%d to %d" % (first[n].year, max(r[2] for r in repos if r[0] == n).year)) for n in lanes))
    return svg(W, H, label, "\n".join(o), t)


def stacks(data, t):
    groups = data["stacks"]
    rows = max(len(g["items"]) for g in groups)
    cw, gap, top = 256, 12, 82
    ch = 70 + rows * 30 + 10
    H = top + ch + 24
    up = sum(1 for g in groups for it in g["items"] if it[2])
    down = sum(1 for g in groups for it in g["items"] if not it[2])
    o = [panel(W, H, t)]
    o.append(text(24, 40, "Stacks", 17, 650, "ink"))
    o.append(text(24, 61, "%d stacks. %d things running, %d stopped but still installed." % (len(groups), up, down), 12.5, 400, "ink2"))
    for i, g in enumerate(groups):
        x = 24 + i * (cw + gap)
        o.append(card(x, top, cw, ch, t))
        o.append(tile("layers", x + 14, top + 14, t, 36))
        on = sum(1 for it in g["items"] if it[2])
        o.append(text(x + 62, top + 29, g["name"], 14.5, 650, "ink"))
        o.append(text(x + 62, top + 46, "%d of %d running" % (on, len(g["items"])), 12, 400, "ink2"))
        for j, (name, note, alive) in enumerate(g["items"]):
            y = top + 82 + j * 30
            if alive:
                o.append('<circle class="pulse" style="animation-delay:%.1fs" cx="%s" cy="%s" r="3.6" fill="%s"/>' % ((i * 4 + j) * 0.35, x + 22, y - 4, t["green"]))
            o.append('<circle cx="%s" cy="%s" r="3.6" fill="%s"/>' % (x + 22, y - 4, t["green"] if alive else t["idle"]))
            o.append(text(x + 36, y, name, 13, 600, "ink" if alive else "ink2"))
            o.append(text(x + cw - 16, y, note, 11.5, 400, "ink3", "end"))
    label = "Stacks. " + " ".join("%s: %s." % (g["name"], ", ".join(it[0] + ("" if it[2] else " (stopped)") for it in g["items"])) for g in groups)
    return svg(W, H, label, "\n".join(o), t)


def button(label, t):
    w, h = 156, 44
    o = ['<rect x=".5" y=".5" width="%s" height="%s" rx="11" fill="%s" stroke="%s"/>' % (w - 1, h - 1, t["card"], t["edge"])]
    o.append('<circle class="pulse" cx="20" cy="22" r="3.6" fill="%s"/><circle cx="20" cy="22" r="3.6" fill="%s"/>' % (t["blue"], t["blue"]))
    o.append(text(34, 26.5, label, 13.5, 600, "ink"))
    o.append('<path d="M%s 26.500l7-7m-5.500 0h5.500v5.500" fill="none" stroke="%s" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' % (w - 27, t["ink3"]))
    return svg(w, h, label, "\n".join(o), t)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="draw from the saved numbers, skip the GitHub API")
    args = ap.parse_args()
    data = json.loads(DATA.read_text())
    if not args.offline:
        refresh(data, os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        DATA.write_text(pretty(data) + "\n")
    OUT.mkdir(exist_ok=True)
    for mode, t in THEMES.items():
        (OUT / ("hero-%s.svg" % mode)).write_text(hero(data, t))
        (OUT / ("timeline-%s.svg" % mode)).write_text(timeline(data, t))
        (OUT / ("stacks-%s.svg" % mode)).write_text(stacks(data, t))
        for key, label in data["buttons"]:
            (OUT / ("btn-%s-%s.svg" % (key, mode))).write_text(button(label, t))
    print("drew %d files into %s" % (len(list(OUT.glob("*.svg"))), OUT.relative_to(ROOT)))


if __name__ == "__main__":
    main()
