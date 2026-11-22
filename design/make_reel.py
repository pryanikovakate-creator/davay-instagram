#!/usr/bin/env python3
"""Рилс из видео Екатерины + подпись со страницы материала на сайте.

    python3 design/make_reel.py <видео> <адрес-материала> <ГГГГ-ММ-ДДTЧЧ:ММ> [папка]

Видео перекодируется под требования Инстаграма: 1080×1920, H.264, AAC, 30 к/с.
Горизонтальное видео ставится по центру, сверху и снизу — размытое то же видео.
Звук остаётся как был. Подпись — название, возраст и описание со страницы материала,
затем «Скачать бесплатно — ссылка в шапке профиля» и хэштеги.
Публикуются только бесплатные материалы.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    st = d["streams"][0]
    w, h = st["width"], st["height"]
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        rot = abs(int(sd.get("rotation", 0)))
    if rot in (90, 270):
        w, h = h, w
    return w, h, float(d["format"]["duration"])


def encode(src, dst, max_seconds=90):
    w, h, dur = probe(src)
    vertical = abs(w / h - 9 / 16) < 0.03
    if vertical:
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p"
        args = ["-vf", vf]
    else:
        fc = ("[0:v]split=2[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:3,eq=brightness=0.04[bg];"
              "[b]scale=1080:-2[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]")
        args = ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, *args,
           "-t", str(min(dur, max_seconds)),
           "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "22", "-maxrate", "8M", "-bufsize", "16M",
           "-g", "60", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)
    return dur > max_seconds


def reel_caption(m):
    meta = " · ".join(x for x in (m["age"], m["format"].replace(" · PDF", "")) if x)
    full = site_post.caption(m)
    tags = full.rsplit("\n\n", 1)[-1]
    head = f"{m['title']}\n{meta}\n\n{m['description']}" if meta else f"{m['title']}\n\n{m['description']}"
    return head + site_post.TAIL + "\n\n" + tags


def build(video, slug, when, folder=None):
    m = site_post.material(slug)  # падает, если материал не бесплатный
    date = when[:10]
    out = Path(folder) if folder else ROOT / "posts" / "drafts" / f"{date}-reel-{slug}"
    out.mkdir(parents=True, exist_ok=True)
    cut = encode(video, str(out / "reel.mp4"))
    meta = {"publish_at": f"{when}:00+03:00", "type": "reel", "video": "reel.mp4",
            "caption": reel_caption(m), "thumb_offset_ms": 1500}
    (out / "post.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "source.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, m, cut


if __name__ == "__main__":
    out, m, cut = build(*sys.argv[1:5])
    size = (out / "reel.mp4").stat().st_size / 1e6
    print(out, "—", m["title"], f"({size:.1f} МБ)" + (" — обрезано до 90 с" if cut else ""))
