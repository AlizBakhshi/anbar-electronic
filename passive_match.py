"""تطبیق پارامتری قطعه‌های عمومی (مقاومت، خازن، سلف، کریستال، LED، فیوز) با محصولات لیون.

۱) کاتالوگ: جدول مشخصات صفحه‌های دسته‌های پسیو لیون خوانده و در جدول lion_catalog ذخیره می‌شود.
۲) مشخصات هر قطعه‌ی عمومی از نامش استخراج می‌شود (مقدار، پکیج، تلرانس، ولتاژ، …).
۳) مقایسه: «دقیق» = همه‌ی مشخصاتی که روی برچسب شما هست یکی باشد و پکیج مبهم نباشد؛
   «سازگار» = قابل استفاده ولی متفاوت (مثلاً تلرانس بهتر یا ولتاژ بالاتر)؛ بین گزینه‌ها ارزان‌ترین.
"""
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import lion_client as lion

# ---------------------------------------------------------------- دسته‌های لیون
CATS = {
    145: "SMD-Resistors", 143: "Current-Sense-Resistors", 144: "Resistor-Networks-And-Array",
    140: "SMD-Ceramic-Capacitors", 141: "SMD-Tantalum-Capacitors", 139: "SMD-Aluminum-Electrolytic-Capacitors",
    385: "Aluminum-Electrolytic-Capacitors---Leaded", 467: "Film-Capacitor", 209: "Fixed-Inductors",
    265: "Ferrite-Beads", 148: "Crystals", 225: "Color-LEDs", 98: "White-SMD-LEDs", 205: "Disposable-Fuses",
}

SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
PKG = ("0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512", "3225", "2520", "5032", "2835", "5050")
DEFAULT_RES_TOL = 1.0   # مقاومتی که تلرانسش روی برچسب نیست = ۱٪
TANTAL_CASE = {"A": "1206", "B": "1210", "C": "2312", "D": "2917", "E": "2917"}


def qty(text, unit_chars, mega_is_milli=False):
    """'4.7KΩ' -> 4700 ؛ '100nF' -> 1e-7 ؛ unit_chars: حروف واحد مجاز بعد از پیشوند"""
    if not text:
        return None
    t = text.replace(",", ".").replace("µ", "u").replace("μ", "u")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([pnumkKMG]?)\s*(?:" + unit_chars + r")?(?![a-zA-Z0-9])", t)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*([pnumkKMG])", t)
        if not m:
            return None
    pre = m.group(2)
    if mega_is_milli and pre == "M":
        pre = "m"
    return float(m.group(1)) * SI.get(pre, 1)


def close(a, b, rel=0.012):
    return a is not None and b is not None and abs(a - b) <= rel * max(abs(a), abs(b), 1e-15)


def pct(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text or "")
    return float(m.group(1)) if m else None


def volts(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*V(?:DC)?(?![A-Za-z])", text or "")
    return float(m.group(1)) if m else None


def pkg_of(text):
    for p in PKG:
        if re.search(r"(?<!\d)" + p + r"(?!\d)", text or ""):
            return p
    return None


def dims(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x*×]\s*(\d+(?:\.\d+)?)", text or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


# ---------------------------------------------------------------- کاتالوگ
def _parse_listing(html, cat_id):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        return []
    heads = [re.sub(r"\s+", " ", th.get_text()).strip() for th in table.find_all("th")]
    items = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2 or not tr.get("data-id"):
            continue
        a = tds[0].select_one("a.part-number") or tds[0].find("a", href=re.compile(r"/products/\d+-"))
        if a is None:
            continue
        href = a["href"]
        brand = tds[0].select_one("a.brand_tag img")
        thumb = tds[0].select_one(".product-thumb img")
        ds = tds[0].find("a", href=re.compile(r"/uploads/catalog/"))
        desc = [lion.clean(p.get_text(" ")) for p in tds[0].select(".short-description-in-list p")]
        tiers = []
        for row in tds[1].select(".pdct-price-row"):
            q = row.select_one(".pdct-quantity")
            pr = row.select_one(".new-price")
            if q is not None and pr is not None:
                tiers.append((int(lion.parse_number(q.get("data-id") or q.get_text())), lion.parse_number(pr.get_text())))
        tiers.sort()
        stock = tds[1].select_one(".prd-quantity")
        attrs = {}
        for h, td in zip(heads[2:], tds[2:]):
            attrs[h] = lion.clean(td.get_text(" "))
        items.append({
            "pid": int(tr["data-id"]), "url": urljoin(lion.BASE_URL, href), "pn": lion.clean(a.get_text()),
            "brand": brand.get("alt", "") if brand is not None else "", "desc": " | ".join(x for x in desc if x),
            "thumb": urljoin(lion.BASE_URL, thumb["src"]) if thumb is not None and thumb.get("src") else "",
            "datasheet": urljoin(lion.BASE_URL, ds["href"]) if ds is not None else "",
            "tiers": tiers, "price": tiers[0][1] if tiers else None, "moq": tiers[0][0] if tiers else None,
            "stock": int(lion.parse_number(stock.get_text())) if stock is not None else None,
            "cat": cat_id, "attrs": attrs,
        })
    return items


def crawl_catalog(progress=None, session=None):
    s = session or requests.Session()
    s.headers.update(lion.HEADERS)
    out, seen = [], set()
    total = len(CATS)
    for n, (cid, slug) in enumerate(CATS.items(), 1):
        for page in range(1, 60):
            if progress:
                progress(n - 1, total, f"خواندن کاتالوگ لیون: {slug.replace('-', ' ')} — صفحه {page}")
            r = s.get(f"{lion.BASE_URL}/category/{cid}-{slug}", params={"page": page}, timeout=30)
            if r.status_code != 200:
                break
            items = [i for i in _parse_listing(r.text, cid) if i["pid"] not in seen]
            if not items:
                break
            for i in items:
                seen.add(i["pid"])
            out.extend(items)
    if progress:
        progress(total, total, "")
    return out


def save_catalog(db, items):
    db.conn.execute("""CREATE TABLE IF NOT EXISTS lion_catalog (
        pid INTEGER PRIMARY KEY, cat INTEGER, pn TEXT, data TEXT, fetched_at TEXT)""")
    db.conn.execute("DELETE FROM lion_catalog")
    from db import now
    db.conn.executemany("INSERT INTO lion_catalog(pid, cat, pn, data, fetched_at) VALUES(?,?,?,?,?)",
                        [(i["pid"], i["cat"], i["pn"], json.dumps(i, ensure_ascii=False), now()) for i in items])
    db.conn.commit()


def load_catalog(db, max_age_days=7):
    db.conn.execute("""CREATE TABLE IF NOT EXISTS lion_catalog (
        pid INTEGER PRIMARY KEY, cat INTEGER, pn TEXT, data TEXT, fetched_at TEXT)""")
    row = db.q1("SELECT MIN(fetched_at) AS t, COUNT(*) AS n FROM lion_catalog")
    if not row["n"]:
        return None
    from datetime import datetime, timedelta
    try:
        if datetime.strptime(row["t"][:19], "%Y-%m-%d %H:%M:%S") < datetime.now() - timedelta(days=max_age_days):
            return None
    except ValueError:
        return None
    return [json.loads(r["data"]) for r in db.q("SELECT data FROM lion_catalog")]


# ---------------------------------------------------------------- مشخصات قطعه‌ی شما
def parse_part(pn):
    """'Resistor 10KΩ 0805 1%' -> {'kind': 'res', 'value': 10000, 'pkg': '0805', 'tol': 1}"""
    t = pn.replace("µ", "u").replace("μ", "u")
    low = t.lower()
    spec = {}
    if low.startswith("shunt resistor"):
        spec = {"kind": "shunt", "value": qty(t.split(" ", 2)[2], "Ω|R|ohm", mega_is_milli=True),
                "pkg": pkg_of(t), "power": qty(re.search(r"\d+(?:\.\d+)?\s*W", t).group() if re.search(r"\d+(?:\.\d+)?\s*W", t) else "", "W")}
    elif low.startswith("resistor"):
        body = t[len("resistor"):]
        if re.search(r"axial|tht|dip|through", low):  # مقاومت پایه‌دار؛ دسته‌ی SMD لیون مناسبش نیست
            return None
        spec = {"kind": "array" if "array" in low else "res", "value": qty(body, "Ω|R|ohm"),
                "pkg": pkg_of(body), "tol": pct(body)}
        if spec["kind"] == "res" and spec["tol"] is None and spec["value"]:  # 0Ω (جامپر) تلرانس ندارد
            spec["tol"] = DEFAULT_RES_TOL  # در این کارگاه مقاومت‌ها ۱٪ هستند
        # 'Resistor 1K 0805' (بدون Ω) هم معتبر است
    elif low.startswith("capacitor"):
        body = t[len("capacitor"):]
        val = qty(body, "F")
        if "tantal" in low:
            m = re.search(r"tantal(?:um)?\s+([A-E])\b", t, re.I)
            spec = {"kind": "tantal", "value": val, "volt": volts(body), "case": m.group(1).upper() if m else None,
                    "pkg": pkg_of(body)}
        elif re.search(r"mkt|400v|630v|film", low):
            spec = {"kind": "film", "value": val, "volt": volts(body)}
        elif re.search(r"electrolytic|solid|\d+(?:\.\d+)?\s*[x*]\s*\d", low):
            d = dims(body)
            if not d:
                m = re.search(r"SMD\s*(\d{2})(\d{2})", body)
                d = (float(m.group(1)), float(m.group(2))) if m else None
            spec = {"kind": "elec", "value": val, "volt": volts(body), "dims": d}
        else:
            spec = {"kind": "cap", "value": val, "pkg": pkg_of(body), "volt": volts(body), "tol": pct(body)}
    elif low.startswith("inductor"):
        body = t[len("inductor"):]
        cur = re.search(r"(\d+(?:\.\d+)?)\s*(m?A)\b", body)
        spec = {"kind": "ind", "value": qty(body, "H"), "pkg": pkg_of(body),
                "current": (float(cur.group(1)) * (1e-3 if cur.group(2) == "mA" else 1)) if cur else None}
    elif low.startswith("crystal"):
        body = t[len("crystal"):]
        f = qty(body, "Hz|HZ|hz")
        if f is not None and f < 1000 and re.search(r"\d\s*M", body):
            f *= 1e6
        spec = {"kind": "xtal", "value": f, "pkg": pkg_of(body)}
    elif low.startswith("led "):
        body = t[4:]
        color = body.split()[0].lower() if body.split() else ""
        spec = {"kind": "led", "color": color, "pkg": pkg_of(body) or ("3mm" if "3mm" in low else "5mm" if "5mm" in low else None)}
    elif low.startswith("fuse ") and not low.startswith("fuse holder"):
        body = t[5:]
        spec = {"kind": "fuse", "value": qty(body, "A"), "pkg": pkg_of(body)}
    if not spec or (spec.get("kind") not in ("led",) and spec.get("value") is None):
        return None
    return spec


# ---------------------------------------------------------------- مقایسه
def _attr(item, *names):
    for n in names:
        v = item["attrs"].get(n)
        if v and v != "-":
            return v
    return ""


def _check(spec, it):
    """(کاندید معتبر؟, دقیق؟, توضیح تفاوت)"""
    k = spec["kind"]
    notes = []
    exact = True
    if k in ("res", "shunt", "array"):
        cats = {"res": (145,), "shunt": (143,), "array": (144,)}[k]
        if it["cat"] not in cats:
            return False, False, ""
        if k == "array":
            v = _attr(it, "Resistor Values")
            m = re.search(r"x\s*(.+)$", v)
            if not close(spec["value"], qty(m.group(1) if m else v, "Ω")):
                return False, False, ""
            pk = _attr(it, "Package/Case")
        else:
            if not close(spec["value"], qty(_attr(it, "Resistance"), "Ω")):
                return False, False, ""
            pk = _attr(it, "Case Code - in")
        if spec.get("pkg"):
            if spec["pkg"] not in pk:
                return False, False, ""
        tol = pct(_attr(it, "Tolerance"))
        if spec.get("tol") is not None and tol is not None and tol != spec["tol"]:
            if tol > spec["tol"]:
                return False, False, ""
            exact = False
            notes.append(f"تلرانس {tol:g}٪ به‌جای {spec['tol']:g}٪")
        if k == "shunt" and spec.get("power"):
            pw = qty(_attr(it, "Power Rating"), "W")
            if pw is not None and pw < spec["power"]:
                return False, False, ""
            if pw is not None and not close(pw, spec["power"]):
                exact = False
                notes.append(f"توان {pw:g}W")
        return True, exact, "، ".join(notes)
    if k in ("cap", "tantal", "elec", "film"):
        cats = {"cap": (140,), "tantal": (141,), "elec": (139, 385), "film": (467,)}[k]
        if it["cat"] not in cats or not close(spec["value"], qty(_attr(it, "Capacitance"), "F")):
            return False, False, ""
        v = volts(_attr(it, "Voltage Rating DC"))
        if spec.get("volt"):
            if v is not None and v < spec["volt"]:
                return False, False, ""
            if v is not None and not close(v, spec["volt"]):
                exact = False
                notes.append(f"ولتاژ {v:g}V به‌جای {spec['volt']:g}V")
        if k == "cap" and spec.get("pkg") and spec["pkg"] not in _attr(it, "Case Code - in"):
            return False, False, ""
        if k == "cap" and spec.get("tol") is not None:
            tol = pct(_attr(it, "Tolerance"))
            if tol is not None and tol > spec["tol"]:
                exact = False
                notes.append(f"تلرانس {tol:g}٪")
        if k == "tantal":
            mfr = _attr(it, "Mfr Case Code")
            code = _attr(it, "Case Code - in")
            if spec.get("case"):
                if not (mfr.upper().startswith(spec["case"]) or TANTAL_CASE.get(spec["case"]) == code):
                    return False, False, ""
            elif spec.get("pkg") and spec["pkg"] != code:
                return False, False, ""
        if k == "elec":
            dia, hei = qty(_attr(it, "Diameter"), "mm"), qty(_attr(it, "Height"), "mm")
            if spec.get("dims"):
                a, b = spec["dims"]
                ok = (close(dia, a, 0.05) and close(hei, b, 0.08)) or (close(dia, b, 0.05) and close(hei, a, 0.08))
                if not ok:
                    exact = False
                    notes.append(f"ابعاد {_attr(it, 'Diameter')}×{_attr(it, 'Height')}")
            if it["cat"] == 385:
                exact = False
                notes.append("پایه‌دار (THT)")
        return True, exact, "، ".join(notes)
    if k == "ind":
        if it["cat"] != 209 or not close(spec["value"], qty(_attr(it, "Inductance"), "H")):
            return False, False, ""
        pk = _attr(it, "Package/Case")
        if spec.get("pkg") and spec["pkg"] not in pk:
            return False, False, ""
        if spec.get("current"):
            c = qty(_attr(it, "Saturation Current"), "A")
            if c is not None and c < spec["current"]:
                return False, False, ""
        return True, exact, ""
    if k == "xtal":
        if it["cat"] != 148 or not close(spec["value"], qty(_attr(it, "Frequency"), "Hz"), 0.01):
            return False, False, ""
        if spec.get("pkg") and spec["pkg"] not in _attr(it, "Package/Case"):
            return False, False, ""
        return True, exact, ""
    if k == "led":
        if it["cat"] not in (225, 98):
            return False, False, ""
        if spec["color"] not in _attr(it, "Illumination Color").lower():
            return False, False, ""
        pk = _attr(it, "Package/Case")
        if spec.get("pkg") and spec["pkg"] not in pk:
            return False, False, ""
        return True, exact, ""
    if k == "fuse":
        if it["cat"] != 205 or not close(spec["value"], qty(_attr(it, "Current Rating"), "A")):
            return False, False, ""
        if spec.get("pkg") and spec["pkg"] not in _attr(it, "Fuse Size\\Group"):
            return False, False, ""
        return True, exact, ""
    return False, False, ""


def _pkg_key(it):
    return _attr(it, "Case Code - in", "Package/Case", "Mfr Case Code", "Fuse Size\\Group") or (
        f"{_attr(it, 'Diameter')}x{_attr(it, 'Height')}")


def price_key(it):
    in_stock = 0 if (it.get("stock") is None or it["stock"] > 0) else 1
    return (in_stock, it["price"] if it.get("price") else 1e18, it.get("moq") or 0)


def match(spec, catalog):
    """-> (status, [(item, exact, note)] مرتب‌شده: اول دقیق‌ها، بعد ارزان‌ترین)"""
    cands = []
    for it in catalog:
        ok, exact, note = _check(spec, it)
        if ok:
            cands.append((it, exact, note))
    if not cands:
        return "none", []
    # اگر پکیج روی برچسب نیست و گزینه‌ها پکیج‌های مختلف دارند، تصمیم با شماست
    if not spec.get("pkg") and not spec.get("case") and not spec.get("dims"):
        if len({_pkg_key(c[0]) for c in cands}) > 1:
            cands = [(it, False, (note + "، " if note else "") + f"پکیج {_pkg_key(it)}") for it, _, note in cands]
    cands.sort(key=lambda c: (not c[1],) + price_key(c[0]))
    return ("exact" if cands[0][1] else "compatible"), cands


def apply_match(db, part_id, it, download=True):
    """قطعه را به محصول لیون وصل می‌کند (نام عمومی قطعه حفظ می‌شود)."""
    from db import now
    p = db.get_part(part_id)
    upd = {"purchase_link": it["url"], "lion_pn": it["pn"], "lion_id": str(it["pid"]),
           "datasheet": it.get("datasheet") or p["datasheet"], "enriched_at": now()}
    if it.get("brand") and not p["manufacturer"]:
        upd["manufacturer"] = it["brand"]
    if it.get("moq"):
        upd["lion_moq"] = it["moq"]
    pk = _attr(it, "Case Code - in", "Package/Case", "Mfr Case Code")
    if pk and not (p["package"] or "").strip():
        upd["package"] = pk
    if it.get("thumb"):
        upd["image_url"] = it["thumb"].replace("/thumbs/", "/")
    if not p["category_id"] or p["category_id"] not in db.categories() or p["category_id"] != it["cat"]:
        upd["category_id"] = it["cat"]
    specs = dict(it["attrs"])
    specs.pop("Packaging", None)
    if it.get("tiers"):
        specs["قیمت پلکانی لیون (ریال)"] = "  ·  ".join(f"{q}+: {int(pr):,}" for q, pr in it["tiers"])
    if it.get("stock") is not None:
        specs["موجودی لیون"] = f"{it['stock']:,}"
    specs["پارت نامبر لیون"] = it["pn"]
    upd["specs"] = json.dumps(specs, ensure_ascii=False)
    if it.get("price") and not p["unit_price"]:
        upd["unit_price"] = it["price"]
        db.add_price(part_id, it["price"], "lion_site", f"{it['pn']} (۱ عدد)")
    db.update_part_fields(part_id, **upd)
    if it.get("thumb") and download:
        try:
            import images
            images.save_thumb(part_id, upd["image_url"])
        except Exception:  # noqa: BLE001
            try:
                import images
                images.save_thumb(part_id, it["thumb"])
            except Exception:  # noqa: BLE001
                pass


def generic_parts(db, part_ids=None):
    """قطعه‌های عمومی که هنوز لینک لیون ندارند و مشخصاتشان قابل خواندن است."""
    rows = db.list_parts() if part_ids is None else [db.get_part(i) for i in part_ids]
    out = []
    for p in rows:
        if not p or "lionelectronic.ir/products/" in (p["purchase_link"] or ""):
            continue
        spec = parse_part(p["part_number"])
        if spec:
            out.append((p, spec))
    return out


def download_images(pairs, workers=6):
    """pairs: [(part_id, catalog_item)] — عکس‌ها به‌صورت موازی."""
    from concurrent.futures import ThreadPoolExecutor
    import images

    def one(pair):
        pid, it = pair
        for url in (it["thumb"].replace("/thumbs/", "/"), it["thumb"]):
            try:
                images.save_thumb(pid, url)
                return
            except Exception:  # noqa: BLE001
                continue
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, [x for x in pairs if x[1].get("thumb")]))
