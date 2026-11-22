#!/usr/bin/env python3
"""Публикатор «Давай узнаем» для Инстаграма.

Запускается GitHub Actions каждый час. Берёт посты из posts/queue/,
у которых наступило время publish_at, и публикует их через официальный
Instagram API (Instagram API with Instagram Login).

Режимы:
  python publish.py            — опубликовать всё, чему пришло время
  python publish.py --check    — проверить ключ доступа, ничего не публикуя
  python publish.py --refresh  — продлить ключ доступа (печатает новый ключ в stdout)

Переменные окружения:
  IG_TOKEN       — ключ доступа (long-lived token) из кабинета разработчика Meta
  REPO_RAW_BASE  — адрес, по которому Инстаграм скачает картинки, например
                   https://raw.githubusercontent.com/<логин>/<репозиторий>/<коммит>
  IG_API_BASE    — адрес API (по умолчанию https://graph.facebook.com/v22.0 — для ключа
                   «единого входа» Meta; для старых ключей Instagram Login —
                   https://graph.instagram.com)
  IG_USER_ID     — номер аккаунта Инстаграма (необязательно: программа найдёт его сама)
  DRY_RUN=1      — ничего не отправлять, только показать, что было бы опубликовано
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "posts"
QUEUE, PUBLISHED, FAILED = POSTS / "queue", POSTS / "published", POSTS / "failed"
API = (os.environ.get("IG_API_BASE") or "https://graph.facebook.com/v22.0").rstrip("/")
MAX_ATTEMPTS = 3
CAPTION_LIMIT = 2200
MAX_HASHTAGS = 30


class ApiError(Exception):
    pass


def call(method, path, params=None, token=None):
    """Один запрос к API. Возвращает разобранный JSON или бросает ApiError."""
    params = dict(params or {})
    if token:
        params["access_token"] = token
    url = f"{API}/{path.lstrip('/')}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except ValueError:
            msg = body
        raise ApiError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"нет связи с API: {e.reason}") from None


def account(token):
    """Находим аккаунт Инстаграма, от имени которого публикуем: (id, username)."""
    fixed = os.environ.get("IG_USER_ID", "").strip()
    if fixed:
        info = call("GET", fixed, {"fields": "id,username"}, token)
        return info.get("id", fixed), info.get("username", "?")
    if "graph.instagram.com" in API:
        me = call("GET", "me", {"fields": "user_id,username"}, token)
        if "user_id" in me:
            return me["user_id"], me.get("username", "?")
        raise ApiError(f"API не вернул user_id: {me}")
    # Ключ системного пользователя (единый вход Meta)
    try:
        r = call("GET", "me/assigned_instagram_accounts", {"fields": "id,username"}, token)
        if r.get("data"):
            a = r["data"][0]
            return a["id"], a.get("username", "?")
    except ApiError:
        pass
    r = call("GET", "me/accounts", {"fields": "instagram_business_account{id,username}"}, token)
    for page in r.get("data", []):
        a = page.get("instagram_business_account")
        if a:
            return a["id"], a.get("username", "?")
    raise ApiError("ключ работает, но к нему не привязан аккаунт Инстаграма. "
                   "Проверьте, что в конфигурации выбран аккаунт «Давай узнаем»")


def wait_ready(container_id, token, tries=20, pause=3):
    """Ждём, пока Инстаграм скачает и обработает картинку."""
    for _ in range(tries):
        st = call("GET", container_id, {"fields": "status_code,status"}, token)
        code = st.get("status_code")
        if code in (None, "FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(f"Инстаграм не принял файл: {st.get('status', code)}")
        time.sleep(pause)
    raise ApiError("Инстаграм слишком долго обрабатывает файл")


def load_post(folder):
    meta = json.loads((folder / "post.json").read_text(encoding="utf-8"))
    kind = meta.get("type", "feed")
    images = meta.get("images") or sorted(p.name for p in folder.glob("*.jpg"))
    problems = []
    if kind not in ("feed", "story"):
        problems.append(f"неизвестный type «{kind}» (нужно feed или story)")
    if not images:
        problems.append("нет картинок .jpg")
    for name in images:
        if not name.lower().endswith((".jpg", ".jpeg")):
            problems.append(f"{name}: Инстаграм принимает только JPG")
        elif not (folder / name).exists():
            problems.append(f"{name}: файла нет в папке")
    if kind == "feed" and len(images) > 10:
        problems.append("в карусели не больше 10 картинок")
    if kind == "story" and len(images) != 1:
        problems.append("в сторис ровно одна картинка")
    caption = meta.get("caption", "")
    if len(caption) > CAPTION_LIMIT:
        problems.append(f"подпись длиннее {CAPTION_LIMIT} знаков")
    if caption.count("#") > MAX_HASHTAGS:
        problems.append(f"больше {MAX_HASHTAGS} хэштегов")
    try:
        when = datetime.fromisoformat(meta["publish_at"])
        if when.tzinfo is None:
            problems.append("в publish_at нет часового пояса, например +03:00")
    except (KeyError, ValueError):
        when = None
        problems.append("publish_at не указан или в неверном формате (пример: 2026-11-24T10:00:00+03:00)")
    return meta, kind, images, caption, when, problems


def publish(folder, token, ig_id, raw_base):
    meta, kind, images, caption, _, _ = load_post(folder)
    rel = folder.relative_to(ROOT).as_posix()
    urls = [f"{raw_base}/{urllib.parse.quote(rel)}/{urllib.parse.quote(n)}" for n in images]
    if kind == "story":
        c = call("POST", f"{ig_id}/media", {"image_url": urls[0], "media_type": "STORIES"}, token)["id"]
    elif len(urls) == 1:
        c = call("POST", f"{ig_id}/media", {"image_url": urls[0], "caption": caption}, token)["id"]
    else:
        children = []
        for u in urls:
            cid = call("POST", f"{ig_id}/media", {"image_url": u, "is_carousel_item": "true"}, token)["id"]
            wait_ready(cid, token)
            children.append(cid)
        c = call("POST", f"{ig_id}/media",
                 {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption}, token)["id"]
    wait_ready(c, token)
    media_id = call("POST", f"{ig_id}/media_publish", {"creation_id": c}, token)["id"]
    link = None
    try:
        link = call("GET", media_id, {"fields": "permalink"}, token).get("permalink")
    except ApiError:
        pass
    return media_id, link


def move(folder, dest_root, extra):
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / folder.name
    if dest.exists():
        dest = dest_root / f"{folder.name}-{int(time.time())}"
    shutil.move(str(folder), str(dest))
    (dest / "result.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def run_queue():
    token = os.environ.get("IG_TOKEN", "")
    raw_base = os.environ.get("REPO_RAW_BASE", "").rstrip("/")
    dry = os.environ.get("DRY_RUN") == "1"
    now = datetime.now(timezone.utc)
    QUEUE.mkdir(parents=True, exist_ok=True)
    due, report = [], []
    for folder in sorted(p for p in QUEUE.iterdir() if p.is_dir()):
        if not (folder / "post.json").exists():
            continue
        _, _, _, _, when, problems = load_post(folder)
        if problems:
            if not dry:
                move(folder, FAILED, {"error": "; ".join(problems), "at": now.isoformat()})
            report.append(f"✗ {folder.name}: {'; '.join(problems)}")
            continue
        if when <= now:
            due.append(folder)
    if not due:
        report.append("Сейчас публиковать нечего.")
        print("\n".join(report))
        return 0
    if dry:
        for f in due:
            report.append(f"[проверка] опубликовал бы: {f.name}")
        print("\n".join(report))
        return 0
    if not token or not raw_base:
        print("Нет IG_TOKEN или REPO_RAW_BASE — проверьте секреты репозитория.")
        return 1
    ig_id, username = account(token)
    for folder in due:
        attempts_file = folder / ".attempts"
        attempts = int(attempts_file.read_text()) if attempts_file.exists() else 0
        try:
            media_id, link = publish(folder, token, ig_id, raw_base)
            attempts_file.unlink(missing_ok=True)
            move(folder, PUBLISHED, {"media_id": media_id, "permalink": link,
                                     "account": username, "at": datetime.now(timezone.utc).isoformat()})
            report.append(f"✓ {folder.name} → {link or media_id}")
        except ApiError as e:
            attempts += 1
            if attempts >= MAX_ATTEMPTS:
                attempts_file.unlink(missing_ok=True)
                move(folder, FAILED, {"error": str(e), "attempts": attempts,
                                      "at": datetime.now(timezone.utc).isoformat()})
                report.append(f"✗ {folder.name}: {e} (попыток: {attempts}, перенесено в failed)")
            else:
                attempts_file.write_text(str(attempts))
                report.append(f"… {folder.name}: {e} (попытка {attempts} из {MAX_ATTEMPTS}, повторю через час)")
    print("\n".join(report))
    return 0


def main(argv):
    token = os.environ.get("IG_TOKEN", "")
    if "--check" in argv:
        ig_id, username = account(token)
        lim = call("GET", f"{ig_id}/content_publishing_limit", {"fields": "quota_usage,config"}, token)
        print(f"Ключ работает. Аккаунт: @{username}. Лимит публикаций: {json.dumps(lim, ensure_ascii=False)}")
        return 0
    if "--refresh" in argv:
        if "graph.instagram.com" not in API:
            print("Ключ системного пользователя бессрочный — продлевать не нужно.", file=sys.stderr)
            return 2
        r = call("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"}, token)
        new = r.get("access_token")
        if not new:
            raise ApiError(f"не удалось продлить ключ: {r}")
        days = int(r.get("expires_in", 0)) // 86400
        print(new)
        print(f"Ключ продлён на {days} дн.", file=sys.stderr)
        return 0
    return run_queue()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ApiError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
