"""اتصال به سایت lionelectronic.ir: ورود، خواندن لیست سفارش‌ها و جزئیات هر سفارش.

ساختار صفحه‌ها (از روی HTML واقعی سایت):
  لیست سفارش‌ها:  /profile/orders/index?page=N  →  div.order-card[data-key]
  جزئیات سفارش:   /profile/orders/view/<id>     →  table.product-list-factor
      هر ردیف: a.invoice-product-link (پارت نامبر) + div.invoice-product-short-description
"""
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://lionelectronic.ir"
ORDERS_URL = "/profile/orders/index"
CART_URL = "https://lionelectronic.ir/orders/cart"
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_html")
MAX_PAGES = 50

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
}

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class LoginError(Exception):
    pass


def to_en_digits(text):
    return (text or "").translate(_FA_DIGITS)


def parse_number(text):
    """'۱۲,۵۰۰ ریال' -> 12500.0"""
    t = to_en_digits(text).replace("٬", "").replace(",", "").replace("،", "")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else 0.0


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ------------------------------------------------------------------ parsers
def parse_order_list(html):
    """[{code, url, date, status, total}] از یک صفحه‌ی لیست سفارش‌ها."""
    soup = BeautifulSoup(html, "lxml")
    orders = []
    for card in soup.select("div.order-card"):
        link = card.select_one("a.order-header-link") or card.find("a", href=True)
        code = card.get("data-key") or ""
        if not code and link:
            m = re.search(r"/view/(\d+)", link["href"])
            code = m.group(1) if m else ""
        if not code:
            continue
        info = {"code": code, "url": urljoin(BASE_URL, link["href"]) if link else
                f"{BASE_URL}/profile/orders/view/{code}", "date": "", "total": "",
                "status": clean(card.select_one(".order-status").get_text()) if card.select_one(".order-status") else ""}
        for row in card.select(".order-info-row"):
            label = row.select_one(".order-info-label")
            value = row.select_one(".order-info-value")
            if not label or not value:
                continue
            label, value = clean(label.get_text()), clean(value.get_text(" "))
            if "تاریخ" in label:
                info["date"] = value
            elif "مبلغ" in label:
                info["total"] = value
        orders.append(info)
    return orders


def parse_order_items(html):
    """اقلام فاکتور: [{part_number, description, quantity, unit_price, total_price, link}]"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.product-list-factor")
    if table is None:
        return []
    items = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        prod = tr.select_one(".invoice-product-cell")
        if prod is None or len(cells) < 4:
            continue
        a = prod.select_one("a.invoice-product-link") or prod.find("a")
        desc_div = prod.select_one(".invoice-product-short-description")
        if a is not None:
            part_number = clean(a.get_text())
            link = urljoin(BASE_URL, a.get("href", ""))
        else:
            name_tag = prod.select_one(".invoice-product-name")
            part_number = clean((name_tag or prod).get_text(" ")).split(" ")[0]
            link = ""
        desc = ""
        if desc_div is not None:
            parts = [clean(p.get_text(" ")) for p in desc_div.find_all(["p", "div", "li"]) if clean(p.get_text(" "))]
            desc = " | ".join(parts) if parts else clean(desc_div.get_text(" "))
        # ستون‌های عددی بعد از ستون کالا: تعداد، واحد (فی)، مجموع
        idx = cells.index(prod) if prod in cells else 2
        nums = [clean(c.get_text(" ")) for c in cells[idx + 1:]]
        qty = int(parse_number(nums[0])) if len(nums) > 0 else 0
        if not part_number or qty <= 0:
            continue
        items.append({
            "part_number": part_number,
            "description": desc,
            "quantity": qty,
            "unit_price": parse_number(nums[1]) if len(nums) > 1 else 0,
            "total_price": parse_number(nums[2]) if len(nums) > 2 else 0,
            "link": link,
        })
    return items


# ------------------------------------------------------------------ client
class LionClient:
    def __init__(self, username, password, captcha_callback=None, log=print):
        self.username = username
        self.password = password
        self.captcha_callback = captcha_callback  # bytes تصویر را می‌گیرد، متن کد را برمی‌گرداند
        self.log = log
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.logged_in = False

    def _get(self, path, **kw):
        r = self.session.get(urljoin(BASE_URL, path), timeout=30, **kw)
        r.raise_for_status()
        return r

    @staticmethod
    def _dump(name, html):
        os.makedirs(DEBUG_DIR, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", name)[:80]
        with open(os.path.join(DEBUG_DIR, safe + ".html"), "w", encoding="utf-8") as f:
            f.write(html)

    @staticmethod
    def _is_login_page(resp):
        return "/login" in resp.url or 'id="login-form"' in resp.text

    def login(self):
        r = self._get("/login")
        for attempt in range(3):
            soup = BeautifulSoup(r.text, "lxml")
            form = soup.find("form", id="login-form")
            if form is None:
                self.logged_in = True
                return True
            data = {inp["name"]: inp.get("value", "") for inp in form.find_all("input")
                    if inp.get("name") and inp.get("type") != "checkbox"}
            data["LoginForm[username]"] = self.username
            data["LoginForm[password]"] = self.password
            data["LoginForm[rememberMe]"] = "1"

            cap_input = form.find("input", attrs={"name": re.compile(r"verify", re.I)})
            if cap_input is not None:
                img = form.find("img", id=re.compile("verifycode", re.I)) or form.find("img")
                if not img or not self.captcha_callback:
                    raise LoginError("سایت کد امنیتی (کپچا) خواسته است.")
                code = self.captcha_callback(self._get(img.get("src")).content)
                if not code:
                    raise LoginError("کد امنیتی وارد نشد.")
                data[cap_input["name"]] = code

            r = self.session.post(urljoin(BASE_URL, "/login"), data=data, timeout=30,
                                  headers={"Referer": urljoin(BASE_URL, "/login")})
            if not self._is_login_page(r):
                self.logged_in = True
                self.log("ورود به سایت لیون موفق بود.")
                return True
            errors = [clean(e.get_text()) for e in
                      BeautifulSoup(r.text, "lxml").select(".help-block-error, .invalid-feedback, .alert-danger")]
            msg = next((e for e in errors if e), "")
            if msg and "کد" not in msg and "captcha" not in msg.lower():
                raise LoginError("ورود ناموفق: " + msg)
            self.log("ورود ناموفق، تلاش دوباره... " + msg)
        self._dump("login_failed", r.text)
        raise LoginError("ورود به سایت ناموفق بود.")

    def fetch_order_list(self, limit=None, known=None, progress=None, cancelled=None):
        """صفحه‌های لیست سفارش‌ها (جدیدترین اول) را می‌خواند.
        limit: حداکثر تعداد سفارش (None = همه). با limit، اگر یک صفحه‌ی کامل از سفارش‌های قبلاً ثبت‌شده
        (known) بود، بقیه‌ی صفحه‌ها خوانده نمی‌شوند. progress(page, found) بعد از هر صفحه صدا زده می‌شود."""
        if not self.logged_in:
            self.login()
        orders, seen = [], set()
        known = known or set()
        for page in range(1, MAX_PAGES + 1):
            if cancelled and cancelled():
                break
            r = self._get(ORDERS_URL, params={"page": page})
            if self._is_login_page(r):
                raise LoginError("نشست منقضی شد؛ دوباره تلاش کنید.")
            found = [o for o in parse_order_list(r.text) if o["code"] not in seen]
            if not found:
                if page == 1:
                    self._dump("orders_list", r.text)
                    self.log("هیچ سفارشی در صفحه سفارش‌ها پیدا نشد (debug_html/orders_list.html).")
                break
            for o in found:
                seen.add(o["code"])
            orders.extend(found)
            if progress:
                progress(page, len(orders))
            if limit and len(orders) >= limit:
                orders = orders[:limit]
                break
            if limit and all(o["code"] in known for o in found):
                break
        self.log(f"{len(orders)} سفارش از حساب کاربری خوانده شد.")
        return orders

    def add_to_cart(self, product_id, quantity):
        """مثل دکمه‌ی «افزودن به سبد خرید» سایت: POST /orders/add  →  (موفق؟, پیام, تعداد اقلام سبد)"""
        if not self.logged_in:
            self.login()
        if not getattr(self, "_csrf", None):
            page = self._get("/orders/cart")
            if self._is_login_page(page):
                self.logged_in = False
                raise LoginError("نشست منقضی شد؛ دوباره تلاش کنید.")
            meta = BeautifulSoup(page.text, "lxml").find("meta", attrs={"name": "csrf-token"})
            self._csrf = meta["content"] if meta else ""
        token = self._csrf
        r = self.session.post(urljoin(BASE_URL, "/orders/add"),
                              data={"product_id": product_id, "quantity": quantity, "_csrf-frontend": token},
                              headers={"X-CSRF-Token": token, "X-Requested-With": "XMLHttpRequest",
                                       "Referer": CART_URL}, timeout=30, allow_redirects=False)
        if r.status_code in (301, 302) and "login" in r.headers.get("Location", ""):
            self.logged_in = False
            self._csrf = None
            raise LoginError("نشست منقضی شد؛ دوباره تلاش کنید.")
        if r.status_code != 200:
            self._dump(f"cart_{product_id}", r.text)
            return False, f"خطای سایت ({r.status_code})", None
        soup = BeautifulSoup(r.text, "lxml")
        total = soup.find("input", id="totalCount")
        msg = clean(soup.get_text(" "))[:160]
        bad = any(w in msg for w in ("موجودی کافی", "ناموجود", "خطا", "حداقل", "امکان"))
        if bad:
            return False, msg, None
        return True, msg, (int(parse_number(total.get("value"))) if total is not None else None)

    def cart_product_ids(self):
        """شناسه‌ی محصولاتی که الان در سبد خرید حساب هستند (برای اطمینان از افزوده شدن)."""
        r = self._get("/orders/cart")
        if self._is_login_page(r):
            raise LoginError("نشست منقضی شد؛ دوباره تلاش کنید.")
        self._dump("cart_page", r.text)
        soup = BeautifulSoup(r.text, "lxml")
        # فقط لینک‌های داخل ردیف‌هایی که دکمه‌ی حذف/تعداد دارند (نه منو و پیشنهادها)
        ids = set()
        for a in soup.find_all("a", href=re.compile(r"/products/\d+-")):
            box = a.find_parent(lambda t: t.name in ("tr", "div", "li") and t.find("input") is not None)
            if box is not None:
                ids.add(int(re.search(r"/products/(\d+)-", a["href"]).group(1)))
        return ids

    def fetch_order_items(self, order):
        r = self._get(order["url"])
        items = parse_order_items(r.text)
        if not items:
            self._dump("order_" + order["code"], r.text)
            self.log(f"اقلام سفارش {order['code']} خوانده نشد (debug_html/order_{order['code']}.html).")
        return items


# ------------------------------------------------------------------ public pages (بدون نیاز به ورود)
def _public_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _cat_id(href):
    m = re.search(r"/category/(\d+)", href or "")
    return int(m.group(1)) if m else None


def fetch_categories(session=None):
    """درخت دسته‌بندی سایت: [{id, name, parent_id, level, count}]"""
    s = session or _public_session()
    r = s.get(urljoin(BASE_URL, "/products/category"), timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    root = soup.select_one("ul.menu-category-1")
    if root is None:
        return []
    cats = []
    for li1 in root.find_all("li", class_="menu-title-1", recursive=False):
        a1 = li1.find("a", class_="menu-link-1")
        id1 = _cat_id(a1.get("href") if a1 else "")
        if not id1:
            continue
        head = li1.select_one("a.menu-category-link-2 span")
        cats.append({"id": id1, "name": clean(a1.get_text()), "parent_id": None, "level": 1,
                     "count": int(parse_number(head.get_text())) if head else 0})
        for li2 in li1.select("li.menu-title-2"):
            a2 = li2.find("a", class_="menu-link-2")
            id2 = _cat_id(a2.get("href") if a2 else "")
            if not id2:
                continue
            name2 = clean((a2.select_one(".menu-text") or a2).get_text())
            cats.append({"id": id2, "name": name2, "parent_id": id1, "level": 2, "count": 0})
            for li3 in li2.select("li.menu-title-3"):
                a3 = li3.find("a", href=True)
                id3 = _cat_id(a3.get("href") if a3 else "")
                if not id3:
                    continue
                cnt = li3.select_one(".menu-count")
                cats.append({"id": id3, "name": clean((a3.select_one(".menu-text") or a3).get_text()),
                             "parent_id": id2, "level": 3,
                             "count": int(parse_number(cnt.get_text())) if cnt else 0})
    return cats


def fetch_product_info(url, session=None):
    """دسته، سازنده، دیتاشیت، پکیج و مشخصات فنی از صفحه‌ی محصول."""
    s = session or _public_session()
    r = s.get(urljoin(BASE_URL, url), timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    info = {"url": r.url, "categories": [], "specs": {}}
    og = soup.find("meta", property="og:image")
    img = og.get("content") if og else None
    if not img:
        tag = soup.select_one("img[src*='/uploads/products/']")
        img = tag.get("src") if tag else None
    if img and "/uploads/products/" in img:
        info["image"] = urljoin(BASE_URL, img)
    parent, level = None, 0
    for a in soup.select("ul.breadcrumb a[href*='/category/']"):
        cid = _cat_id(a["href"])
        if not cid:
            continue
        level += 1
        info["categories"].append({"id": cid, "name": clean(a.get_text()), "parent_id": parent, "level": level})
        parent = cid
    info["category_id"] = parent
    for row in soup.select(".product-detail .detail-row"):
        key = clean((row.select_one(".detail-value") or row).get_text())
        val_tag = row.select_one(".detail-key")
        if val_tag is None:
            continue
        if key == "Datasheet":
            a = val_tag.find("a", href=True)
            if a:
                info["datasheet"] = urljoin(BASE_URL, a["href"])
        elif key == "Manufacture":
            info["manufacturer"] = clean(val_tag.get_text())
        elif key == "Lion Part":
            info["lion_id"] = clean(val_tag.get_text())
        elif key == "Part Number":
            info["part_number"] = clean(val_tag.get_text())
    desc = soup.select_one(".product-detail .product-description")
    if desc:
        parts = [clean(p.get_text(" ")) for p in desc.find_all("p") if clean(p.get_text(" "))]
        info["description"] = " | ".join(parts)
    for item in soup.select(".spec-item"):
        # در سایت، کلاس‌های label و value برعکس استفاده شده‌اند
        val, name = item.select_one(".spec-label"), item.select_one(".spec-value")
        if val and name:
            info["specs"][clean(name.get_text())] = clean(val.get_text())
    # جدول قیمت پلکانی: ردیف اول = قیمت خرید تعداد کم (۱ عدد)
    tiers = []
    for row in soup.select(".product-box .price-row"):
        q = row.select_one(".pdct-quantity")
        pr = row.select_one(".new-price") or row.select_one(".price-text")
        if q is None or pr is None:
            continue
        qty, price = int(parse_number(q.get("data-id") or q.get_text())), parse_number(pr.get_text())
        if price > 0:
            tiers.append((qty, price))
    if tiers:
        tiers.sort()
        info["price"] = tiers[0][1]
        info["price_tiers"] = tiers
        info["specs"]["قیمت پلکانی لیون (ریال)"] = "  ·  ".join(f"{q}+: {int(p):,}" for q, p in tiers)
    stock = soup.select_one(".product-box .stock-amount")
    if stock is not None:
        info["lion_stock"] = int(parse_number(stock.get_text()))
        info["specs"]["موجودی لیون"] = f"{info['lion_stock']:,}"
    for k in ("Package-Case", "Package / Case", "Package", "Case"):
        if info["specs"].get(k):
            info["package"] = info["specs"][k]
            break
    return info


def search_product(part_number, session=None, allow_prefix=False):
    """آدرس صفحه‌ی محصولی که پارت نامبرش دقیقاً برابر است (یا None).
    با allow_prefix: (url, exact) — اگر دقیق نبود، کوتاه‌ترین محصولی که با پارت نامبر شروع می‌شود."""
    s = session or _public_session()
    r = s.get(urljoin(BASE_URL, "/products"), params={"search": part_number, "searchMode": "text"}, timeout=30)
    r.raise_for_status()
    from urllib.parse import unquote

    def norm(t):
        return re.sub(r"[^a-z0-9]", "", t.lower())

    want = norm(part_number)
    want_core = norm(re.sub(r"\([^)]*\)", "", part_number))
    prefix = []
    for href in dict.fromkeys(re.findall(r'href="(/products/\d+-[^"]+)"', r.text)):
        raw = unquote(href.split("-", 1)[1] if "-" in href else "")  # %28A1%29 -> (A1)
        slug = norm(raw)
        core = norm(re.sub(r"\([^)]*\)", "", raw))  # پسوند داخل پرانتز، مثل (A1)، کد بسته‌بندی است
        if slug == want or (core and core == want_core):
            return (urljoin(BASE_URL, href), True) if allow_prefix else urljoin(BASE_URL, href)
        if len(want) >= 4 and slug.startswith(want) and len(slug) - len(want) <= 6:
            prefix.append((len(slug), href))
    if allow_prefix:
        return (urljoin(BASE_URL, min(prefix)[1]), False) if prefix else (None, False)
    return None


def product_id_from_link(link):
    """'https://lionelectronic.ir/products/2492-TLV74333PDBVR' -> 2492"""
    m = re.search(r"lionelectronic\.ir/products/(\d+)-", link or "")
    return int(m.group(1)) if m else None


def search_url(part_number):
    from urllib.parse import quote
    return f"{BASE_URL}/products?search={quote(part_number)}&searchMode=text"
