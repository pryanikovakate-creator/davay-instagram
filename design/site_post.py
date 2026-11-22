#!/usr/bin/env python3
"""Пост из бесплатного материала сайта davayuznaem.ru — без придуманного текста.

    python3 design/site_post.py list
        — все бесплатные материалы с сайта (адрес и название)
    python3 design/site_post.py feed  <адрес> <ГГГГ-ММ-ДД> [папка]
    python3 design/site_post.py story <адрес> <ГГГГ-ММ-ДД> [папка]

<адрес> — часть ссылки после /material/, например zimnie-labirinty.
Картинки — превью листов с сайта, целиком, на светлом фоне. Подпись — название,
описание и «Как заниматься» со страницы материала. Пост сохраняется в
posts/drafts/<дата>-<адрес>/ (или в указанную папку).
"""
import html as H
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = "https://davayuznaem.ru"
ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(__file__).resolve().parent / "fonts"
BG = (246, 242, 251)
INK = (38, 35, 51)
PURPLE = (106, 74, 200)
CAPTION_LIMIT = 2200
TAIL = "\n\nСкачать бесплатно — по ссылке в шапке профиля 💛"

TAGS = {
    "math": "#математикадлядетей #счётдлядетей", "letters": "#учимбуквы #азбука",
    "speech": "#развитиеречи #мнемотаблицы", "writing": "#прописи #подготовкарукикписьму",
    "attention": "#логикадлядетей #развитиевнимания", "world": "#окружающиймир",
    "english": "#английскийдлядетей", "creative": "#творчествосдетьми #поделкисдетьми",
    "holidays": "#праздникисдетьми",
}
BASE_TAGS = "#давайузнаем #заданиядлядетей #развивашки #занятиясдетьми"


def get(url, tries=4):
    import time
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "davay-instagram/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:
            if t == tries - 1:
                raise
            time.sleep(2 + 3 * t)


def text_lines(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "\n", s)
    return [l.strip() for l in H.unescape(s).split("\n") if l.strip()]


def free_list():
    s = get(f"{SITE}/catalog/free/").decode("utf-8")
    out = []
    for slug in re.findall(r'href="(?:https://davayuznaem\.ru)?/material/([^/"]+)/"', s):
        if slug not in out:
            out.append(slug)
    return out


def material(slug):
    url = f"{SITE}/material/{slug}/"
    s = get(url).decode("utf-8")
    lines = text_lines(s)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    title = H.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else lines[0]
    if "Бесплатно" not in lines[: lines.index(title) + 8 if title in lines else 40]:
        raise SystemExit(f"{slug}: это не бесплатный материал — не публикуем")
    i = len(lines) - 1 - lines[::-1].index(title) if title in lines else 0
    head = lines[i + 1:i + 8]
    age = next((l for l in head if re.search(r"\d+\s*[–-]\s*\d+\s*(лет|года)", l)), "")
    fmt = next((l for l in head if "лист" in l and "·" in l), "")
    try:
        j = lines.index("⤢ Увеличить", i)
    except ValueError:
        j = lines.index("Бесплатно", i)
    desc = lines[j + 1] if j + 1 < len(lines) else ""
    how = []
    if "Как заниматься" in lines:
        k = lines.index("Как заниматься") + 1
        while k < len(lines) and not lines[k].startswith("Новые материалы выходят") and not lines[k].startswith("Платная"):
            how.append(lines[k])
            k += 1
    topics = sorted(set(re.findall(r'href="/topic/([a-z]+)/"', s[:s.find("Ещё для маленьких") if "Ещё для маленьких" in s else len(s)])))
    previews = sorted(set(re.findall(rf"/previews/{re.escape(slug)}/(\d+)\.jpg", s)), key=int)
    if not previews:
        raise SystemExit(f"{slug}: на странице нет превью листов")
    return {"slug": slug, "url": url, "title": title, "age": age, "format": fmt, "description": desc,
            "how": how, "topics": topics, "previews": [f"{SITE}/previews/{slug}/{n}.jpg" for n in previews]}


KEYWORD_TAGS = [
    (r"матер|мам", "#деньматери #подарокмаме"), (r"нов\w* год|ёлоч|new year", "#новыйгод #новогодниезадания"),
    (r"зим", "#зимниезадания"), (r"осен", "#осенниезадания"), (r"счит|счёт|числ|цифр|математ", "#математикадлядетей"),
    (r"букв|азбук|алфавит", "#учимбуквы"), (r"пропис|обвод|дорожк|письм", "#прописи"),
    (r"мнемотабл", "#мнемотаблицы"), (r"english|английск", "#английскийдлядетей"),
    (r"вырез|поделк|аппликац|открытк", "#поделкисдетьми"), (r"раскраск|рису", "#рисуемсдетьми"),
    (r"лабиринт|найди|внимани|шульте", "#развитиевнимания"),
]


def caption(m):
    found = [TAGS[t] for t in m["topics"] if t in TAGS]
    hay = (m["title"] + " " + m["description"]).lower()
    found += [t for rx, t in KEYWORD_TAGS if re.search(rx, hay)]
    words = []
    for t in " ".join([BASE_TAGS] + found).split():
        if t not in words:
            words.append(t)
    tags = " ".join(words[:10])
    meta = " · ".join(x for x in (m["age"], m["format"].replace(" · PDF", "")) if x)
    head = f"{m['title']}\n{meta}\n\n{m['description']}" if meta else f"{m['title']}\n\n{m['description']}"
    how = list(m["how"])
    while True:
        body = head + ("\n\nКак заниматься:\n" + "\n\n".join(how) if how else "")
        full = body + TAIL + "\n\n" + tags
        if len(full) <= CAPTION_LIMIT or not how:
            return full[:CAPTION_LIMIT]
        how.pop()  # убираем последние абзацы, если подпись не помещается


def sheet_on(canvas_size, sheet, box_h, top=None):
    W, Hh = canvas_size
    c = Image.new("RGB", canvas_size, BG)
    k = box_h / sheet.height
    s = sheet.resize((round(sheet.width * k), round(sheet.height * k)), Image.LANCZOS)
    x = (W - s.width) // 2
    y = (Hh - s.height) // 2 if top is None else top
    sh = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([x + 6, y + 14, x + s.width + 6, y + s.height + 14], fill=(60, 40, 110, 60))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    c.paste(sh, (0, 0), sh)
    c.paste(s, (x, y))
    return c


def font(size, weight=900):
    try:
        return ImageFont.truetype(str(FONTS / f"Nunito-{weight}.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def text_c(d, xy, text, f, fill):
    """Текст по центру; пробелы рисуем сами — в файле шрифта только кириллица."""
    words = text.split()
    gap = f.size * 0.28
    widths = [d.textlength(w, font=f) for w in words]
    x = xy[0] - (sum(widths) + gap * (len(words) - 1)) / 2
    for w, wd in zip(words, widths):
        d.text((x, xy[1]), w, font=f, fill=fill, anchor="lm")
        x += wd + gap


def build(kind, slug, date, folder=None):
    m = material(slug)
    out = Path(folder) if folder else ROOT / "posts" / "drafts" / f"{date}-{slug}"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    sheets = [Image.open(io.BytesIO(get(u))).convert("RGB") for u in m["previews"]]
    if kind == "feed":
        for n, sh in enumerate(sheets[:10], 1):
            sheet_on((1080, 1350), sh, 1250).save(out / f"{n}.jpg", quality=92)
        meta = {"publish_at": f"{date}T10:00:00+03:00", "type": "feed", "caption": caption(m),
                "images": [f"{n}.jpg" for n in range(1, min(len(sheets), 10) + 1)]}
    else:
        img = sheet_on((1080, 1920), sheets[0], 1420, top=330)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([90, 160, 400, 250], 45, fill=PURPLE)
        d.text((245, 205), "Бесплатно", font=font(46), fill="white", anchor="mm")
        text_c(d, (540, 1830), "ссылка в шапке профиля", font(44, 800), INK)
        img.save(out / "1.jpg", quality=92)
        meta = {"publish_at": f"{date}T10:00:00+03:00", "type": "story", "caption": "", "images": ["1.jpg"]}
    (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "source.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, m


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        for slug in free_list():
            print(slug)
    else:
        out, m = build(a[0], a[1], a[2], a[3] if len(a) > 3 else None)
        print(out, "—", m["title"], f"({len(m['previews'])} лист.)")
