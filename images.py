"""عکس قطعه‌ها: دانلود یک‌باره از لیون، کوچک‌سازی به ۳۰۰×۳۰۰ و نگه‌داری در پوشه‌ی images کنار دیتابیس."""
import io
import os

import requests
from PIL import Image

import db as dbm

THUMB = 300
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36"}


def image_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(dbm.DB_PATH)), "images")
    os.makedirs(d, exist_ok=True)
    return d


def thumb_path(part_id):
    return os.path.join(image_dir(), f"{int(part_id)}.jpg")


def has_thumb(part_id):
    return os.path.exists(os.path.join(os.path.dirname(os.path.abspath(dbm.DB_PATH)), "images", f"{int(part_id)}.jpg"))


def to_jpeg(data, size=THUMB):
    """بایت‌های عکس -> JPEG کوچک‌شده با پس‌زمینه‌ی سفید (برای PNGهای شفاف)."""
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if size:
        im.thumbnail((size, size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def fetch(url, session=None, timeout=30):
    s = session or requests
    r = s.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def save_thumb(part_id, url, session=None, overwrite=False):
    """عکس را دانلود و کوچک می‌کند. True اگر فایل ساخته شد."""
    path = thumb_path(part_id)
    if os.path.exists(path) and not overwrite:
        return False
    data = to_jpeg(fetch(url, session))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return True


def delete_thumbs(part_ids):
    for pid in part_ids:
        try:
            os.remove(thumb_path(pid))
        except OSError:
            pass
