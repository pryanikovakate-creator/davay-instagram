#!/usr/bin/env python3
"""Генератор слайдов «Давай узнаем» для Инстаграма.

    python3 design/make_post.py spec.json posts/drafts/2026-11-23-znakomstvo

spec.json:
{
  "publish_at": "2026-11-23T10:00:00+03:00",
  "caption": "…",
  "slides": [
    {"type": "cover", "kicker": "Давайте знакомиться", "title": "Привет! Я *Екатерина*", "text": "…"},
    {"type": "text",  "title": "…", "text": "…"},
    {"type": "list",  "title": "…", "items": [{"title": "…", "text": "…"}], "start": 1},
    {"type": "final", "title": "…", "text": "…"}
  ]
}
*слово* в заголовке выделяется фиолетовым. Пустая строка в text — новый абзац.
Сохраняет 1.jpg, 2.jpg… (1080×1350) и post.json в папку поста.
Нужен Playwright с Chromium (в облаке Claude он уже есть: /opt/pw-browsers).
"""
import base64
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1080, 1350

C = {"ink": "#262333", "purple": "#6A4AC8", "grey": "#8A8494", "sun": "#FBBE4A",
     "sun_soft": "#FFF1C9", "leaf": "#8DC04C", "lav": "#B482E8", "paper": "#FCFAFE", "lav_soft": "#F1EAFC"}


def font_face():
    out = []
    for w in (400, 700, 800, 900):
        for sub in ("cyrillic", "latin"):
            f = HERE / "fonts" / f"nunito-{sub}-{w}-normal.woff2"
            if f.exists():
                b64 = base64.b64encode(f.read_bytes()).decode()
                out.append(f"@font-face{{font-family:Nunito;font-weight:{w};src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "\n".join(out)


def icon_svg(size):
    src = (HERE / "logo.svg").read_text(encoding="utf-8")
    defs = re.search(r"<defs>.*?</defs>", src, re.S).group(0)
    body = re.search(r'<g id="icon"[^>]*>(.*?)</g>\s*<path fill="#262333"', src, re.S).group(1)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="140 95 500 480" width="{size}" height="{size * 480 / 500:.0f}">'
            f"{defs}{body}</svg>")


def rich(t):
    t = html.escape(t)
    return re.sub(r"\*(.+?)\*", r'<em>\1</em>', t)


def paras(t):
    return "".join(f"<p>{rich(p.strip())}</p>" for p in re.split(r"\n\s*\n", t or "") if p.strip())


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%(W)spx;height:%(H)spx}
body{font-family:Nunito,sans-serif;color:%(ink)s;background:%(paper)s;-webkit-font-smoothing:antialiased}
.s{position:relative;width:%(W)spx;height:%(H)spx;overflow:hidden;padding:84px 88px 92px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:14px;font-weight:900;font-size:34px;letter-spacing:-.01em}
.brand em{font-style:normal;color:%(purple)s}
.count{margin-left:auto;font-weight:700;font-size:28px;color:%(grey)s;font-variant-numeric:tabular-nums}
.foot{position:absolute;left:88px;right:88px;bottom:56px;display:flex;justify-content:space-between;font-weight:700;font-size:26px;color:%(grey)s}
h1{font-weight:900;font-size:92px;line-height:1.02;letter-spacing:-.025em;text-wrap:balance}
h2{font-weight:900;font-size:68px;line-height:1.06;letter-spacing:-.02em;text-wrap:balance}
h1 em,h2 em{font-style:normal;color:%(purple)s}
.kicker{display:inline-block;align-self:flex-start;font-weight:800;font-size:28px;letter-spacing:.08em;text-transform:uppercase;color:%(purple)s;background:%(lav_soft)s;padding:10px 20px;border-radius:999px}
.txt p{font-size:48px;line-height:1.36;font-weight:400}
.txt p+p{margin-top:26px}
.txt b{font-weight:800}
.cover{background:%(sun_soft)s}
.cover .main{margin-top:auto;display:flex;flex-direction:column;gap:34px;padding-bottom:40px}
.cover .txt p{font-size:44px}
.cover .big{position:absolute;right:-60px;top:150px;opacity:.95}
.text .main{margin-top:auto;margin-bottom:auto;display:flex;flex-direction:column;gap:52px}
.text h2{font-size:96px}
.list .main{margin-top:auto;margin-bottom:auto;display:flex;flex-direction:column;gap:72px}
.list h2{font-size:80px}
.items{display:flex;flex-direction:column;gap:64px}
.it{display:grid;grid-template-columns:120px 1fr;column-gap:36px;align-items:start}
.n{width:120px;height:120px;border-radius:50%%;background:%(sun)s;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:60px;color:%(ink)s}
.it h3{font-weight:800;font-size:58px;line-height:1.1;margin-top:10px}
.it p{font-size:44px;line-height:1.32;margin-top:14px}
.note{font-size:36px;line-height:1.3;color:%(purple)s;font-weight:800;background:%(lav_soft)s;padding:26px 32px;border-radius:24px;margin-bottom:48px}
.final{background:%(purple)s;color:#fff}
.final .brand,.final .foot,.final .count{color:#fff}
.final .brand em{color:#FFD877}
.final .main{margin-top:auto;margin-bottom:auto;display:flex;flex-direction:column;gap:40px}
.final h2{font-size:96px}
.final h2 em{color:#FFD877}
.final .txt p{font-size:48px;opacity:.92}
.dots{position:absolute;inset:auto auto 0 0;pointer-events:none}
"""


def frame(kind, inner, idx, total, small_icon):
    count = f'<span class="count">{idx}/{total}</span>' if total > 1 else ""
    return (f'<div class="s {kind}"><div class="brand">{small_icon}<span>Давай <em>узнаем</em></span>{count}</div>'
            f'{inner}<div class="foot"><span>davayuznaem.ru</span><span>{"листайте →" if idx < total else ""}</span></div></div>')


def slide_html(sl, idx, total):
    small = icon_svg(64)
    t = sl["type"]
    if t == "cover":
        inner = (f'<div class="big">{icon_svg(560)}</div><div class="main">'
                 + (f'<span class="kicker">{rich(sl["kicker"])}</span>' if sl.get("kicker") else "")
                 + f'<h1>{rich(sl["title"])}</h1><div class="txt">{paras(sl.get("text", ""))}</div></div>')
    elif t == "text":
        inner = f'<div class="main"><h2>{rich(sl["title"])}</h2><div class="txt">{paras(sl.get("text", ""))}</div></div>'
        if sl.get("note"):
            inner += f'<div class="note">{rich(sl["note"])}</div>'
    elif t == "list":
        n0 = sl.get("start", 1)
        items = "".join(
            f'<div class="it"><div class="n">{n0 + i}</div><div><h3>{rich(it["title"])}</h3>'
            + (f'<p>{rich(it["text"])}</p>' if it.get("text") else "") + "</div></div>"
            for i, it in enumerate(sl["items"]))
        inner = f'<div class="main"><h2>{rich(sl["title"])}</h2><div class="items">{items}</div></div>'
        if sl.get("note"):
            inner += f'<div class="note">{rich(sl["note"])}</div>'
    elif t == "final":
        inner = f'<div class="main"><h2>{rich(sl["title"])}</h2><div class="txt">{paras(sl.get("text", ""))}</div></div>'
    else:
        raise ValueError(f"неизвестный тип слайда: {t}")
    return frame(t, inner, idx, total, small)


def render(spec, out_dir):
    from playwright.sync_api import sync_playwright
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    style = font_face() + CSS % {"W": W, "H": H, **C}
    slides = spec["slides"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, sl in enumerate(slides, 1):
            doc = f"<!doctype html><html><head><meta charset=utf-8><style>{style}</style></head><body>{slide_html(sl, i, len(slides))}</body></html>"
            pg.set_content(doc)
            pg.evaluate("document.fonts.ready")
            pg.screenshot(path=str(out / f"{i}.jpg"), type="jpeg", quality=92)
        b.close()
    meta = {"publish_at": spec["publish_at"], "type": "feed", "caption": spec["caption"],
            "images": [f"{i}.jpg" for i in range(1, len(slides) + 1)]}
    (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render(spec, sys.argv[2]))
