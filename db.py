"""لایه دیتابیس SQLite برای انبار الکترونیک."""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

import jdatetime

import appinfo

DB_PATH = os.path.join(appinfo.data_dir(), "warehouse.db")

# ستون name در parts و lion_order_items فقط برای سازگاری با نسخه‌ی اول مانده و استفاده نمی‌شود.
SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number TEXT NOT NULL UNIQUE,
    name TEXT,
    category TEXT,
    package TEXT,
    location TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    min_quantity INTEGER NOT NULL DEFAULT 0,
    unit_price REAL DEFAULT 0,
    description TEXT,
    link TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    change INTEGER NOT NULL,
    reason TEXT,
    source TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS lion_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code TEXT NOT NULL UNIQUE,
    order_date TEXT,
    status TEXT,
    total TEXT,
    url TEXT,
    added_to_stock INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT
);
CREATE TABLE IF NOT EXISTS lion_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES lion_orders(id) ON DELETE CASCADE,
    part_number TEXT,
    name TEXT,
    quantity INTEGER,
    unit_price REAL,
    total_price REAL,
    link TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,           -- شناسه‌ی دسته در سایت لیون
    name TEXT NOT NULL,
    parent_id INTEGER,
    level INTEGER NOT NULL DEFAULT 1,
    site_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    price REAL NOT NULL,
    source TEXT,
    ref TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS bom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    part_number TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    designators TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    source TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tr_part ON transactions(part_id);
CREATE INDEX IF NOT EXISTS ix_ph_part ON price_history(part_id);
CREATE INDEX IF NOT EXISTS ix_bom_project ON bom_items(project_id);
CREATE TABLE IF NOT EXISTS cabinets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL UNIQUE,      -- شماره‌ی روی برچسب کابینت (کد مکان با آن شروع می‌شود)
    name TEXT,
    rows INTEGER NOT NULL DEFAULT 10,
    cols INTEGER NOT NULL DEFAULT 5
);
CREATE TABLE IF NOT EXISTS drawers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id INTEGER NOT NULL REFERENCES cabinets(id) ON DELETE CASCADE,
    row INTEGER NOT NULL,                -- از ۱، از بالا
    col INTEGER NOT NULL,                -- از ۰، از چپ (A)
    title TEXT,                          -- سرتیتر برچسب، مثلاً Capacitor
    comps INTEGER NOT NULL DEFAULT 1,    -- تعداد خانه‌های کشو (۱ تا ۳)
    labels TEXT,                         -- JSON: [{"main": "680µF", "sub": "10x10 10V"}, …]
    UNIQUE(cabinet_id, row, col)
);
CREATE TABLE IF NOT EXISTS part_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    drawer_id INTEGER NOT NULL REFERENCES drawers(id) ON DELETE CASCADE,
    comp INTEGER NOT NULL DEFAULT 1,
    UNIQUE(part_id, drawer_id, comp)
);
CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS map_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER REFERENCES areas(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'box',    -- box (میز/دستگاه)، wall (دیوار)، text (نوشته)
    text TEXT,
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    w REAL NOT NULL DEFAULT 4,
    h REAL NOT NULL DEFAULT 2,
    color TEXT
);
CREATE INDEX IF NOT EXISTS ix_loc_part ON part_locations(part_id);
CREATE INDEX IF NOT EXISTS ix_loc_drawer ON part_locations(drawer_id);
"""

SUPPLIER_LION = "لیون الکترونیک"
ORDER_PENDING, ORDER_IN_STOCK, ORDER_IGNORED = 0, 1, 2


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_jalali(ts, with_time=True):
    """'2026-10-05 19:51:18' -> '1405/07/13 19:51'"""
    if not ts:
        return ""
    try:
        g = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S" if len(ts) >= 19 else "%Y-%m-%d %H:%M")
    except ValueError:
        return ts
    j = jdatetime.datetime.fromgregorian(datetime=g)
    return j.strftime("%Y/%m/%d %H:%M" if with_time else "%Y/%m/%d")


def jalali_to_greg(text):
    """'1405/07/13 - 17:25' -> '2026-10-05 17:25:00'"""
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})(?:\D+(\d{1,2}):(\d{2}))?", text or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    try:
        g = jdatetime.datetime(y, mo, d, hh, mm).togregorian()
    except ValueError:
        return ""
    return g.strftime("%Y-%m-%d %H:%M:%S")


def money(text):
    digits = re.sub(r"[^\d]", "", str(text or ""))
    return float(digits) if digits else 0.0


class Database:
    def __init__(self, path=None):
        self.path = path or DB_PATH
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()
        self._cat_cache = None

    def close(self):
        self.conn.close()

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def q1(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def _columns(self, table):
        return {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        cols = self._columns("parts")
        for col, typ in [("purchase_link", "TEXT"), ("category_id", "INTEGER"), ("manufacturer", "TEXT"),
                         ("datasheet", "TEXT"), ("specs", "TEXT"), ("lion_id", "TEXT"), ("enriched_at", "TEXT"),
                         ("needs_count", "INTEGER NOT NULL DEFAULT 0"), ("image_url", "TEXT"),
                         ("lion_moq", "INTEGER"), ("lion_pn", "TEXT")]:
            if col not in cols:
                self.conn.execute(f"ALTER TABLE parts ADD COLUMN {col} {typ}")
                if col == "purchase_link":
                    self.conn.execute("UPDATE parts SET purchase_link = link WHERE COALESCE(link,'') != ''")
        cab_cols = self._columns("cabinets")
        for col, typ in [("pos_x", "REAL"), ("pos_y", "REAL"), ("kind", "TEXT NOT NULL DEFAULT 'drawers'"),
                         ("area_id", "INTEGER"), ("color", "TEXT")]:
            if col not in cab_cols:
                self.conn.execute(f"ALTER TABLE cabinets ADD COLUMN {col} {typ}")
        dr_cols = self._columns("drawers")
        for col in ("row_span", "col_span"):
            if col not in dr_cols:
                self.conn.execute(f"ALTER TABLE drawers ADD COLUMN {col} INTEGER NOT NULL DEFAULT 1")
        if "manual" not in self._columns("categories"):
            self.conn.execute("ALTER TABLE categories ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
        if not self.conn.execute("SELECT 1 FROM areas").fetchone():
            self.conn.execute("INSERT INTO areas(name, sort) VALUES('کارگاه', 0)")
        first_area = self.conn.execute("SELECT id FROM areas ORDER BY sort, id").fetchone()[0]
        self.conn.execute("UPDATE cabinets SET area_id=? WHERE area_id IS NULL OR area_id NOT IN (SELECT id FROM areas)",
                          (first_area,))
        if "qty_before" not in self._columns("transactions"):
            # موجودی قبل/بعد هر ورود و خروج؛ برای سوابق قدیمی از موجودی فعلی به عقب حساب می‌شود
            self.conn.execute("ALTER TABLE transactions ADD COLUMN qty_before INTEGER")
            self.conn.execute("ALTER TABLE transactions ADD COLUMN qty_after INTEGER")
            for (pid,) in self.conn.execute("SELECT DISTINCT part_id FROM transactions").fetchall():
                self.recompute_stock_chain(pid, commit=False)
        if "cart_at" not in self._columns("shopping"):
            self.conn.execute("ALTER TABLE shopping ADD COLUMN cart_at TEXT")
        if "description" not in self._columns("lion_order_items"):
            self.conn.execute("ALTER TABLE lion_order_items ADD COLUMN description TEXT")
            self.conn.execute("UPDATE lion_order_items SET description = name")
        if "order_ts" not in self._columns("lion_orders"):
            self.conn.execute("ALTER TABLE lion_orders ADD COLUMN order_ts TEXT")
            for r in self.conn.execute("SELECT id, order_date FROM lion_orders").fetchall():
                self.conn.execute("UPDATE lion_orders SET order_ts=? WHERE id=?", (jalali_to_greg(r["order_date"]), r["id"]))
        # تاریخچه‌ی قیمت را یک‌بار از سفارش‌های واردشده بساز
        if self.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0:
            self.conn.execute("""
                INSERT INTO price_history(part_id, price, source, ref, created_at)
                SELECT p.id, i.unit_price, 'lion', o.order_code, COALESCE(NULLIF(o.order_ts,''), o.imported_at)
                FROM lion_order_items i JOIN lion_orders o ON o.id = i.order_id
                JOIN parts p ON p.part_number = i.part_number COLLATE NOCASE
                WHERE o.added_to_stock = 1 AND i.unit_price > 0""")

    # ================================================================ settings
    def get_setting(self, key, default=""):
        row = self.q1("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    # ================================================================ categories
    def upsert_categories(self, cats):
        """cats: [{id, name, parent_id, level, count}]"""
        for c in cats:
            self.conn.execute(
                "INSERT INTO categories(id, name, parent_id, level, site_count) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, parent_id=excluded.parent_id, "
                "level=excluded.level, site_count=COALESCE(NULLIF(excluded.site_count,0), site_count)",
                (c["id"], c["name"], c.get("parent_id"), c.get("level", 1), c.get("count", 0)))
        self.conn.commit()
        self._cat_cache = None

    def categories(self):
        """{id: {id, name, parent_id, level, path, top}}"""
        if self._cat_cache is None:
            rows = {r["id"]: dict(r) for r in self.q("SELECT * FROM categories")}
            for c in rows.values():
                chain, cur, guard = [], c, 0
                while cur and guard < 6:
                    chain.append(cur["name"])
                    cur = rows.get(cur["parent_id"])
                    guard += 1
                chain.reverse()
                c["chain"] = chain
                c["path"] = " › ".join(chain)
                c["short"] = " › ".join(chain[-2:])
                c["top"] = chain[0] if chain else ""
            self._cat_cache = rows
        return self._cat_cache

    MANUAL_CAT_BASE = 1_000_000_000   # دسته‌های دستی با شناسه‌ی بزرگ تا با شناسه‌های لیون تداخل نکنند

    def save_category(self, name, parent_id=None, cat_id=None):
        """دسته‌ی دستی (بدون لیون). parent_id = None یعنی دسته‌ی اصلی."""
        level = 1
        if parent_id:
            parent = self.categories().get(parent_id)
            level = (parent["level"] if parent else 0) + 1
        if cat_id:
            self.conn.execute("UPDATE categories SET name=?, parent_id=?, level=? WHERE id=?", (name, parent_id, level, cat_id))
        else:
            mx = self.q1("SELECT MAX(id) FROM categories")[0] or 0
            cat_id = max(mx + 1, self.MANUAL_CAT_BASE)
            self.conn.execute("INSERT INTO categories(id, name, parent_id, level, manual) VALUES(?,?,?,?,1)",
                              (cat_id, name, parent_id, level))
        self.conn.commit()
        self._cat_cache = None
        return cat_id

    def delete_category(self, cat_id):
        """دسته و زیردسته‌هایش حذف می‌شوند؛ قطعه‌ها بدون دسته می‌مانند."""
        ids = list(self.category_descendants(cat_id))
        marks = ",".join("?" * len(ids))
        self.conn.execute(f"UPDATE parts SET category_id=NULL WHERE category_id IN ({marks})", ids)
        self.conn.execute(f"DELETE FROM categories WHERE id IN ({marks})", ids)
        self.conn.commit()
        self._cat_cache = None

    def category_part_counts(self):
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT category_id, COUNT(*) FROM parts WHERE category_id IS NOT NULL GROUP BY category_id")}

    def category_descendants(self, cat_id):
        cats = self.categories()
        children = {}
        for c in cats.values():
            children.setdefault(c["parent_id"], []).append(c["id"])
        out, stack = set(), [cat_id]
        while stack:
            x = stack.pop()
            if x in out:
                continue
            out.add(x)
            stack.extend(children.get(x, []))
        return out

    # ================================================================ parts
    PART_FIELDS = ["part_number", "description", "category_id", "manufacturer", "package", "location",
                   "min_quantity", "unit_price", "purchase_link", "datasheet"]

    def list_parts(self):
        return self.q("SELECT * FROM parts ORDER BY part_number COLLATE NOCASE")

    def part_numbers(self):
        return [r[0] for r in self.conn.execute("SELECT part_number FROM parts ORDER BY part_number COLLATE NOCASE")]

    def distinct(self, column):
        assert column in ("location", "package", "manufacturer")
        return [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM parts WHERE COALESCE({column},'') != '' ORDER BY 1 COLLATE NOCASE")]

    def stats(self):
        return dict(self.q1(
            "SELECT COUNT(*) AS n, COALESCE(SUM(quantity),0) AS qty, "
            "COALESCE(SUM(MAX(quantity,0)*unit_price),0) AS value, "
            "COALESCE(SUM(quantity <= min_quantity AND min_quantity > 0),0) AS low, "
            "COALESCE(SUM(quantity <= 0),0) AS empty FROM parts"))

    def get_part(self, part_id):
        return self.q1("SELECT * FROM parts WHERE id=?", (part_id,))

    def find_part(self, part_number):
        return self.q1("SELECT * FROM parts WHERE part_number=? COLLATE NOCASE", ((part_number or "").strip(),))

    def save_part(self, data, part_id=None):
        fields = self.PART_FIELDS
        defaults = {"min_quantity": 0, "unit_price": 0}
        values = [data.get(f, defaults.get(f)) if data.get(f) is not None else defaults.get(f) for f in fields]
        if part_id:
            old = self.get_part(part_id)
            sets = ", ".join(f"{f}=?" for f in fields)
            self.conn.execute(f"UPDATE parts SET {sets}, updated_at=? WHERE id=?", values + [now(), part_id])
            if old and float(old["unit_price"] or 0) != float(data.get("unit_price") or 0) and data.get("unit_price"):
                self.add_price(part_id, data["unit_price"], "manual")
        else:
            cols = ", ".join(fields + ["quantity", "created_at", "updated_at"])
            marks = ", ".join("?" * (len(fields) + 3))
            cur = self.conn.execute(f"INSERT INTO parts({cols}) VALUES({marks})", values + [0, now(), now()])
            part_id = cur.lastrowid
            qty = int(data.get("quantity") or 0)
            if qty:
                self.change_stock(part_id, qty, "موجودی اولیه", "manual", commit=False)
            if data.get("unit_price"):
                self.add_price(part_id, data["unit_price"], "manual")
        self.conn.commit()
        return part_id

    def update_part_fields(self, part_id, **fields):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE parts SET {sets} WHERE id=?", list(fields.values()) + [part_id])
        self.conn.commit()

    def recompute_stock_chain(self, part_id, commit=True):
        """موجودی قبل/بعد همه‌ی تراکنش‌های یک قطعه را از موجودی فعلی به عقب دوباره حساب می‌کند."""
        row = self.conn.execute("SELECT quantity FROM parts WHERE id=?", (part_id,)).fetchone()
        if not row:
            return
        running = row[0] or 0
        for tid, ch in self.conn.execute("SELECT id, change FROM transactions WHERE part_id=? ORDER BY id DESC",
                                         (part_id,)).fetchall():
            self.conn.execute("UPDATE transactions SET qty_after=?, qty_before=? WHERE id=?", (running, running - ch, tid))
            running -= ch
        if commit:
            self.conn.commit()

    def rename_part(self, part_id, new_pn):
        """تغییر پارت نامبر همراه با به‌روزرسانی BOM و لیست خرید."""
        p = self.get_part(part_id)
        if not p or p["part_number"] == new_pn:
            return
        for table in ("bom_items", "shopping"):
            self.conn.execute(f"UPDATE {table} SET part_number=? WHERE part_number=? COLLATE NOCASE",
                              (new_pn, p["part_number"]))
        self.conn.execute("UPDATE parts SET part_number=?, updated_at=? WHERE id=?", (new_pn, now(), part_id))
        self.conn.commit()

    def merge_parts(self, src_id, dst_id):
        """قطعه‌ی src در dst ادغام می‌شود: موجودی جمع، محل‌ها، تاریخچه، BOM، لیست خرید و
        فیلدهای خالیِ dst از src پر می‌شود؛ سپس src حذف می‌شود."""
        src, dst = self.get_part(src_id), self.get_part(dst_id)
        if not src or not dst or src_id == dst_id:
            return False
        c = self.conn
        c.execute("INSERT OR IGNORE INTO part_locations(part_id, drawer_id, comp) "
                  "SELECT ?, drawer_id, comp FROM part_locations WHERE part_id=?", (dst_id, src_id))
        c.execute("UPDATE transactions SET part_id=? WHERE part_id=?", (dst_id, src_id))
        c.execute("UPDATE price_history SET part_id=? WHERE part_id=?", (dst_id, src_id))
        for table in ("bom_items", "shopping"):
            c.execute(f"UPDATE {table} SET part_number=? WHERE part_number=? COLLATE NOCASE",
                      (dst["part_number"], src["part_number"]))
        upd = {"quantity": (dst["quantity"] or 0) + (src["quantity"] or 0),
               "min_quantity": max(dst["min_quantity"] or 0, src["min_quantity"] or 0),
               # اگر یکی شمارش شده و دیگری خالی است، نتیجه شمارش‌شده است
               "needs_count": 1 if (dst["needs_count"] and src["needs_count"]) or
                              (dst["needs_count"] and src["quantity"] == 0 and dst["quantity"] == 0) else 0}
        for k in ("description", "category_id", "manufacturer", "package", "location", "purchase_link", "datasheet",
                  "specs", "lion_id", "lion_pn", "lion_moq", "image_url", "unit_price"):
            if not dst[k] and src[k]:
                upd[k] = src[k]
        sets = ", ".join(f"{k}=?" for k in upd)
        c.execute(f"UPDATE parts SET {sets}, updated_at=? WHERE id=?", list(upd.values()) + [now(), dst_id])
        c.execute("DELETE FROM parts WHERE id=?", (src_id,))
        c.commit()
        self.recompute_stock_chain(dst_id)
        try:  # عکس
            import images
            if not images.has_thumb(dst_id) and images.has_thumb(src_id):
                os.replace(images.thumb_path(src_id), images.thumb_path(dst_id))
            else:
                images.delete_thumbs([src_id])
        except Exception:  # noqa: BLE001
            pass
        return True

    def delete_parts(self, part_ids):
        self.conn.executemany("DELETE FROM parts WHERE id=?", [(i,) for i in part_ids])
        self.conn.commit()

    def change_stock(self, part_id, change, reason="", source="manual", commit=True):
        row = self.conn.execute("SELECT quantity FROM parts WHERE id=?", (part_id,)).fetchone()
        before = (row[0] or 0) if row else 0
        self.conn.execute("UPDATE parts SET quantity = quantity + ?, updated_at=? WHERE id=?", (change, now(), part_id))
        self.conn.execute("INSERT INTO transactions(part_id, change, reason, source, created_at, qty_before, qty_after) "
                          "VALUES(?,?,?,?,?,?,?)", (part_id, change, reason, source, now(), before, before + change))
        if commit:
            self.conn.commit()

    def add_price(self, part_id, price, source, ref="", ts=None):
        self.conn.execute("INSERT INTO price_history(part_id, price, source, ref, created_at) VALUES(?,?,?,?,?)",
                          (part_id, float(price), source, ref, ts or now()))

    def price_history(self, part_id):
        return self.q("SELECT * FROM price_history WHERE part_id=? ORDER BY created_at", (part_id,))

    def part_transactions(self, part_id, limit=50):
        return self.q("SELECT * FROM transactions WHERE part_id=? ORDER BY id DESC LIMIT ?", (part_id, limit))

    def list_transactions(self, limit=5000):
        return self.q("SELECT t.*, p.part_number, p.description FROM transactions t "
                      "JOIN parts p ON p.id = t.part_id ORDER BY t.id DESC LIMIT ?", (limit,))

    def parts_to_enrich(self, only_missing=True):
        sql = "SELECT * FROM parts"
        if only_missing:
            sql += " WHERE enriched_at IS NULL"
        return self.q(sql)

    def apply_product_info(self, part_id, info, update_price=False):
        """اطلاعات صفحه‌ی محصول لیون را روی قطعه می‌نشاند (فقط فیلدهای خالی را پر می‌کند، به‌جز دیتاشیت/مشخصات)."""
        p = self.get_part(part_id)
        if not p:
            return
        if info.get("categories"):
            self.upsert_categories(info["categories"])
        upd = {"enriched_at": now()}
        if info.get("category_id") and not p["category_id"]:
            upd["category_id"] = info["category_id"]
        for key, src in [("manufacturer", "manufacturer"), ("package", "package"), ("description", "description")]:
            if info.get(src) and not (p[key] or "").strip():
                upd[key] = info[src]
        if info.get("datasheet"):
            upd["datasheet"] = info["datasheet"]
        if info.get("specs"):
            upd["specs"] = json.dumps(info["specs"], ensure_ascii=False)
        if info.get("lion_id"):
            upd["lion_id"] = info["lion_id"]
        if info.get("url") and not (p["purchase_link"] or "").startswith("http"):
            upd["purchase_link"] = info["url"]
        if info.get("image"):
            upd["image_url"] = info["image"]
        if info.get("price_tiers"):
            upd["lion_moq"] = int(info["price_tiers"][0][0])
        price = info.get("price")
        if price and (update_price or not p["unit_price"]):
            if float(p["unit_price"] or 0) != float(price):
                upd["unit_price"] = price
                self.add_price(part_id, price, "lion_site", "قیمت سایت (۱ عدد)")
        self.update_part_fields(part_id, **upd)

    # ================================================================ storage (کابینت / کشو / خانه)
    @staticmethod
    def col_letter(col):
        return chr(ord("A") + col)

    @classmethod
    def drawer_code(cls, cab_number, row, col):
        return f"{cab_number}-{cls.col_letter(col)}{row}"

    @classmethod
    def loc_code(cls, cab_number, row, col, comp, comps):
        base = cls.drawer_code(cab_number, row, col)
        return base if comps <= 1 else f"{base}-{comp}"

    @staticmethod
    def parse_code(text):
        """'3-B4-1' -> (3, row=4, col=1, comp=1) ؛ '3-B4' -> comp=None"""
        m = re.fullmatch(r"\s*(\d+)\s*-\s*([A-Za-z])\s*(\d+)\s*(?:-\s*(\d))?\s*", text or "")
        if not m:
            return None
        return (int(m.group(1)), int(m.group(3)), ord(m.group(2).upper()) - ord("A"),
                int(m.group(4)) if m.group(4) else None)

    CAB_KINDS = {"drawers": "کابینت کشویی", "shelf": "قفسه‌ی طبقه‌ای", "organizer": "جعبه‌ی خانه‌خانه",
                 "box": "جعبه / کارتن تکی"}

    def list_cabinets(self, area_id=None):
        if area_id is None:
            return self.q("SELECT * FROM cabinets ORDER BY number")
        return self.q("SELECT * FROM cabinets WHERE area_id=? ORDER BY number", (area_id,))

    def get_cabinet(self, cab_id):
        return self.q1("SELECT * FROM cabinets WHERE id=?", (cab_id,))

    def _free_pos(self, area_id):
        """جای خالی سمت راست اشیای همان ناحیه (واحد = یک خانه)."""
        right = 0.0
        for c in self.q("SELECT pos_x, cols FROM cabinets WHERE area_id=?", (area_id,)):
            right = max(right, (c["pos_x"] or 0) + c["cols"] + 1)
        for m in self.q("SELECT x, w FROM map_items WHERE area_id=?", (area_id,)):
            right = max(right, m["x"] + m["w"] + 1)
        return right, 0.0

    def save_cabinet(self, number, name, rows, cols, cab_id=None, kind="drawers", area_id=None, color=None):
        if kind == "box":
            rows, cols = 1, 1
        if cab_id:
            old = self.get_cabinet(cab_id)
            area_id = area_id or old["area_id"]
            self.conn.execute("UPDATE cabinets SET number=?, name=?, rows=?, cols=?, kind=?, area_id=?, color=? WHERE id=?",
                              (number, name, rows, cols, kind, area_id, color, cab_id))
            if old["area_id"] != area_id:
                x, y = self._free_pos(area_id)
                self.conn.execute("UPDATE cabinets SET pos_x=?, pos_y=? WHERE id=?", (x, y, cab_id))
            # کشوهای بیرون از اندازه‌ی جدید حذف می‌شوند و ادغام‌ها داخل کابینت می‌مانند
            self.conn.execute("DELETE FROM drawers WHERE cabinet_id=? AND (row>? OR col>=?)", (cab_id, rows, cols))
            self.conn.execute("UPDATE drawers SET row_span=MIN(row_span, ?-row+1), col_span=MIN(col_span, ?-col) "
                              "WHERE cabinet_id=?", (rows, cols, cab_id))
        else:
            area_id = area_id or self.areas()[0]["id"]
            x, y = self._free_pos(area_id)
            cab_id = self.conn.execute(
                "INSERT INTO cabinets(number, name, rows, cols, kind, area_id, color, pos_x, pos_y) VALUES(?,?,?,?,?,?,?,?,?)",
                (number, name, rows, cols, kind, area_id, color, x, y)).lastrowid
        self.conn.commit()
        return cab_id

    def set_cabinet_pos(self, cab_id, x, y):
        self.conn.execute("UPDATE cabinets SET pos_x=?, pos_y=? WHERE id=?", (x, y, cab_id))
        self.conn.commit()

    def delete_cabinet(self, cab_id):
        self.conn.execute("DELETE FROM cabinets WHERE id=?", (cab_id,))
        self.conn.commit()

    # ---------------------------------------------------------------- areas (اتاق / انبار)
    def areas(self):
        return self.q("SELECT a.*, (SELECT COUNT(*) FROM cabinets c WHERE c.area_id=a.id) AS cab_count "
                      "FROM areas a ORDER BY a.sort, a.id")

    def save_area(self, name, area_id=None):
        if area_id:
            self.conn.execute("UPDATE areas SET name=? WHERE id=?", (name, area_id))
        else:
            sort = (self.q1("SELECT MAX(sort) FROM areas")[0] or 0) + 1
            area_id = self.conn.execute("INSERT INTO areas(name, sort) VALUES(?,?)", (name, sort)).lastrowid
        self.conn.commit()
        return area_id

    def delete_area(self, area_id):
        """ناحیه حذف می‌شود؛ قفسه‌هایش به ناحیه‌ی اول منتقل می‌شوند (هیچ قفسه‌ای حذف نمی‌شود)."""
        rest = [a for a in self.areas() if a["id"] != area_id]
        if not rest:
            return False
        for c in self.list_cabinets(area_id):
            x, y = self._free_pos(rest[0]["id"])
            self.conn.execute("UPDATE cabinets SET area_id=?, pos_x=?, pos_y=? WHERE id=?", (rest[0]["id"], x, y, c["id"]))
        self.conn.execute("DELETE FROM areas WHERE id=?", (area_id,))
        self.conn.commit()
        return True

    # ---------------------------------------------------------------- map items (میز، دیوار، نوشته در نقشه)
    MAP_KINDS = {"box": "میز / دستگاه", "wall": "دیوار", "text": "نوشته"}

    def map_items(self, area_id):
        return self.q("SELECT * FROM map_items WHERE area_id=? ORDER BY id", (area_id,))

    def save_map_item(self, area_id, kind, text, x, y, w, h, color=None, item_id=None):
        if item_id:
            self.conn.execute("UPDATE map_items SET kind=?, text=?, x=?, y=?, w=?, h=?, color=? WHERE id=?",
                              (kind, text, x, y, w, h, color, item_id))
        else:
            item_id = self.conn.execute(
                "INSERT INTO map_items(area_id, kind, text, x, y, w, h, color) VALUES(?,?,?,?,?,?,?,?)",
                (area_id, kind, text, x, y, w, h, color)).lastrowid
        self.conn.commit()
        return item_id

    def set_map_item_geom(self, item_id, x, y, w, h):
        self.conn.execute("UPDATE map_items SET x=?, y=?, w=?, h=? WHERE id=?", (x, y, w, h, item_id))
        self.conn.commit()

    def delete_map_item(self, item_id):
        self.conn.execute("DELETE FROM map_items WHERE id=?", (item_id,))
        self.conn.commit()

    @staticmethod
    def _labels(d):
        try:
            labels = json.loads(d["labels"] or "[]")
        except ValueError:
            labels = []
        labels = [x if isinstance(x, dict) else {"main": str(x), "sub": ""} for x in labels]
        while len(labels) < 3:
            labels.append({"main": "", "sub": ""})
        return labels[:3]

    def cabinet_drawers(self, cab_id):
        """{(row, col): drawer-dict با labels و parts: {comp: [part rows]}}"""
        out = {}
        for d in self.q("SELECT * FROM drawers WHERE cabinet_id=?", (cab_id,)):
            dd = dict(d)
            dd["labels"] = self._labels(d)
            dd["parts"] = {}
            out[(d["row"], d["col"])] = dd
        by_id = {d["id"]: d for d in out.values()}
        if by_id:
            for r in self.q(
                    "SELECT l.drawer_id, l.comp, p.* FROM part_locations l JOIN parts p ON p.id=l.part_id "
                    "JOIN drawers d ON d.id=l.drawer_id WHERE d.cabinet_id=? ORDER BY p.part_number", (cab_id,)):
                by_id[r["drawer_id"]]["parts"].setdefault(r["comp"], []).append(r)
        return out

    def get_drawer(self, drawer_id):
        d = self.q1("SELECT d.*, c.number AS cab_number FROM drawers d JOIN cabinets c ON c.id=d.cabinet_id "
                    "WHERE d.id=?", (drawer_id,))
        if not d:
            return None
        dd = dict(d)
        dd["labels"] = self._labels(d)
        return dd

    _COVER_SQL = ("SELECT * FROM drawers WHERE cabinet_id=? AND row<=? AND row+row_span>? AND col<=? AND col+col_span>? "
                  "ORDER BY (row=? AND col=?) DESC LIMIT 1")

    def drawer_at(self, cab_id, row, col):
        """کشوی خانه‌ی (row, col)؛ اگر خانه زیر یک کشوی ادغام‌شده است، همان کشو."""
        d = self.q1(self._COVER_SQL, (cab_id, row, row, col, col, row, col))
        return self.get_drawer(d["id"]) if d else None

    @staticmethod
    def cover_map(drawers):
        """{(row, col) خانه‌ی پوشیده: (row, col) کشوی اصلی} برای کشوهای ادغام‌شده."""
        out = {}
        for (r, c), d in drawers.items():
            for rr in range(r, r + (d.get("row_span") or 1)):
                for cc in range(c, c + (d.get("col_span") or 1)):
                    if (rr, cc) != (r, c):
                        out[(rr, cc)] = (r, c)
        return out

    def _overlapping(self, cab_id, row, col, row_span, col_span):
        return [d for d in self.q("SELECT * FROM drawers WHERE cabinet_id=? AND NOT (row=? AND col=?)", (cab_id, row, col))
                if d["row"] < row + row_span and d["row"] + d["row_span"] > row
                and d["col"] < col + col_span and d["col"] + d["col_span"] > col]

    def span_conflicts(self, cab_id, row, col, row_span, col_span):
        """کشوهای تعریف‌شده (برچسب یا قطعه دارند) که داخل محدوده‌ی ادغام می‌افتند."""
        out = []
        for d in self._overlapping(cab_id, row, col, row_span, col_span):
            has_parts = self.q1("SELECT 1 FROM part_locations WHERE drawer_id=?", (d["id"],))
            if d["title"] or has_parts or any(l["main"] or l["sub"] for l in self._labels(d)):
                out.append(d)
        return out

    def set_drawer_span(self, cab_id, row, col, row_span, col_span):
        """ادغام/جدا کردن: کشوی (row, col) چند خانه را می‌گیرد و خانه‌های خالیِ زیر آن پاک می‌شوند.
        اگر کشوی پری زیر محدوده باشد، False."""
        cab = self.get_cabinet(cab_id)
        row_span = max(1, min(int(row_span), cab["rows"] - row + 1))
        col_span = max(1, min(int(col_span), cab["cols"] - col))
        if self.span_conflicts(cab_id, row, col, row_span, col_span):
            return False
        for d in self._overlapping(cab_id, row, col, row_span, col_span):
            self.conn.execute("DELETE FROM drawers WHERE id=?", (d["id"],))
        self.conn.execute("INSERT INTO drawers(cabinet_id, row, col, title, comps, labels, row_span, col_span) "
                          "VALUES(?,?,?,'',1,'[]',?,?) ON CONFLICT(cabinet_id, row, col) DO UPDATE SET "
                          "row_span=excluded.row_span, col_span=excluded.col_span",
                          (cab_id, row, col, row_span, col_span))
        self.conn.commit()
        return True

    def save_drawer(self, cab_id, row, col, title, comps, labels):
        comps = max(1, min(3, int(comps or 1)))
        labels = list(labels or [])
        js = json.dumps([{"main": (l.get("main") or "").strip(), "sub": (l.get("sub") or "").strip()}
                         for l in labels[:3]], ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO drawers(cabinet_id, row, col, title, comps, labels) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(cabinet_id, row, col) DO UPDATE SET title=excluded.title, comps=excluded.comps, "
            "labels=excluded.labels", (cab_id, row, col, title, comps, js))
        did = self.q1("SELECT id FROM drawers WHERE cabinet_id=? AND row=? AND col=?", (cab_id, row, col))["id"]
        # قطعه‌های خانه‌هایی که حذف شدند به خانه‌ی آخر منتقل شوند
        self.conn.execute("UPDATE OR IGNORE part_locations SET comp=? WHERE drawer_id=? AND comp>?", (comps, did, comps))
        self.conn.execute("DELETE FROM part_locations WHERE drawer_id=? AND comp>?", (did, comps))
        self.conn.commit()
        return did

    def clear_drawer(self, drawer_id):
        """برچسب و قطعه‌ها پاک می‌شوند؛ اگر کشو ادغام‌شده است، اندازه‌اش می‌ماند."""
        d = self.q1("SELECT * FROM drawers WHERE id=?", (drawer_id,))
        if d and (d["row_span"] > 1 or d["col_span"] > 1):
            self.conn.execute("DELETE FROM part_locations WHERE drawer_id=?", (drawer_id,))
            self.conn.execute("UPDATE drawers SET title='', comps=1, labels='[]' WHERE id=?", (drawer_id,))
        else:
            self.conn.execute("DELETE FROM drawers WHERE id=?", (drawer_id,))
        self.conn.commit()

    def drawer_parts(self, drawer_id):
        return self.q("SELECT l.comp, p.* FROM part_locations l JOIN parts p ON p.id=l.part_id "
                      "WHERE l.drawer_id=? ORDER BY l.comp, p.part_number", (drawer_id,))

    def set_comp_parts(self, drawer_id, comp, part_ids):
        self.conn.execute("DELETE FROM part_locations WHERE drawer_id=? AND comp=?", (drawer_id, comp))
        self.conn.executemany("INSERT OR IGNORE INTO part_locations(part_id, drawer_id, comp) VALUES(?,?,?)",
                              [(pid, drawer_id, comp) for pid in part_ids])
        self.conn.commit()

    def part_locations(self, part_id):
        out = []
        for r in self.q("SELECT l.comp, d.id AS drawer_id, d.row, d.col, d.comps, d.title, "
                        "c.id AS cabinet_id, c.number, c.name FROM part_locations l "
                        "JOIN drawers d ON d.id=l.drawer_id JOIN cabinets c ON c.id=d.cabinet_id "
                        "WHERE l.part_id=? ORDER BY c.number, d.col, d.row", (part_id,)):
            out.append({"code": self.loc_code(r["number"], r["row"], r["col"], r["comp"], r["comps"]),
                        "drawer_id": r["drawer_id"], "cabinet_id": r["cabinet_id"], "title": r["title"] or "",
                        "comp": r["comp"], "cabinet_name": r["name"] or ""})
        return out

    def all_location_codes(self):
        """[(code, توضیح)] برای تکمیل خودکار"""
        out = []
        for r in self.q("SELECT d.*, c.number FROM drawers d JOIN cabinets c ON c.id=d.cabinet_id "
                        "ORDER BY c.number, d.col, d.row"):
            labels = self._labels(r)
            for comp in range(1, r["comps"] + 1):
                lab = labels[comp - 1]
                text = " ".join(x for x in (r["title"] or "", lab["main"], lab["sub"]) if x)
                out.append((self.loc_code(r["number"], r["row"], r["col"], comp, r["comps"]), text))
        return out

    def locations_map(self):
        """{part_id: ['3-B4-1', …]}"""
        out = {}
        for r in self.q("SELECT l.part_id, l.comp, d.row, d.col, d.comps, c.number FROM part_locations l "
                        "JOIN drawers d ON d.id=l.drawer_id JOIN cabinets c ON c.id=d.cabinet_id "
                        "ORDER BY c.number, d.col, d.row"):
            out.setdefault(r["part_id"], []).append(
                self.loc_code(r["number"], r["row"], r["col"], r["comp"], r["comps"]))
        return out

    def resolve_code(self, text, create=False):
        """'3-B4-1' -> (drawer_id, comp) یا None. با create، کشوی خالی ساخته می‌شود."""
        pc = self.parse_code(text)
        if not pc:
            return None
        num, row, col, comp = pc
        cab = self.q1("SELECT * FROM cabinets WHERE number=?", (num,))
        if not cab or not (1 <= row <= cab["rows"]) or not (0 <= col < cab["cols"]):
            return None
        d = self.q1(self._COVER_SQL, (cab["id"], row, row, col, col, row, col))
        if not d:
            if not create:
                return None
            did = self.save_drawer(cab["id"], row, col, "", comp or 1, [])
            d = self.q1("SELECT * FROM drawers WHERE id=?", (did,))
        comp = comp or 1
        if comp > d["comps"]:
            if not create or comp > 3:
                return None
            self.conn.execute("UPDATE drawers SET comps=? WHERE id=?", (comp, d["id"]))
        return d["id"], comp

    def set_part_location_codes(self, part_id, codes):
        """کدهای مکان قطعه را جایگزین می‌کند؛ کدهای نامعتبر برگردانده می‌شوند."""
        bad, pairs = [], []
        for c in codes:
            r = self.resolve_code(c, create=True)
            (pairs.append(r) if r else bad.append(c))
        self.conn.execute("DELETE FROM part_locations WHERE part_id=?", (part_id,))
        self.conn.executemany("INSERT OR IGNORE INTO part_locations(part_id, drawer_id, comp) VALUES(?,?,?)",
                              [(part_id, d, c) for d, c in pairs])
        self.conn.commit()
        return bad

    def drawer_titles(self):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT title FROM drawers WHERE COALESCE(title,'')!='' ORDER BY 1 COLLATE NOCASE")]

    def set_needs_count(self, part_id, value):
        self.conn.execute("UPDATE parts SET needs_count=? WHERE id=?", (1 if value else 0, part_id))
        self.conn.commit()

    # ================================================================ lion orders
    def order_exists(self, order_code):
        return self.q1("SELECT 1 FROM lion_orders WHERE order_code=?", (order_code,)) is not None

    def save_order(self, order, items):
        cur = self.conn.execute(
            "INSERT INTO lion_orders(order_code, order_date, order_ts, status, total, url, imported_at) VALUES(?,?,?,?,?,?,?)",
            (order["code"], order.get("date", ""), jalali_to_greg(order.get("date", "")), order.get("status", ""),
             order.get("total", ""), order.get("url", ""), now()))
        oid = cur.lastrowid
        for it in items:
            self.conn.execute(
                "INSERT INTO lion_order_items(order_id, part_number, description, quantity, unit_price, total_price, link) "
                "VALUES(?,?,?,?,?,?,?)",
                (oid, it["part_number"], it.get("description", ""), it.get("quantity", 0),
                 it.get("unit_price", 0), it.get("total_price", 0), it.get("link", "")))
        self.conn.commit()
        return oid

    def update_order_info(self, order):
        self.conn.execute(
            "UPDATE lion_orders SET status=COALESCE(NULLIF(?,''), status), order_date=COALESCE(NULLIF(?,''), order_date), "
            "total=COALESCE(NULLIF(?,''), total), url=COALESCE(NULLIF(?,''), url) WHERE order_code=?",
            (order.get("status", ""), order.get("date", ""), order.get("total", ""), order.get("url", ""), order["code"]))
        self.conn.commit()

    def get_order(self, order_id):
        return self.q1("SELECT * FROM lion_orders WHERE id=?", (order_id,))

    def list_orders(self):
        return self.q("SELECT o.*, (SELECT COUNT(*) FROM lion_order_items i WHERE i.order_id=o.id) AS item_count "
                      "FROM lion_orders o ORDER BY CAST(o.order_code AS INTEGER) DESC")

    def pending_orders(self):
        return self.q1("SELECT COUNT(*) FROM lion_orders WHERE added_to_stock=0")[0]

    def order_items(self, order_id):
        return self.q("SELECT * FROM lion_order_items WHERE order_id=? ORDER BY id", (order_id,))

    def delete_orders(self, ids):
        self.conn.executemany("DELETE FROM lion_orders WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    def set_order_state(self, order_id, state):
        self.conn.execute("UPDATE lion_orders SET added_to_stock=? WHERE id=?", (state, order_id))
        self.conn.commit()

    def add_order_to_stock(self, order_id):
        """اقلام سفارش را وارد انبار می‌کند. [part_id ...] قطعه‌های درگیر را برمی‌گرداند."""
        order = self.get_order(order_id)
        if not order or order["added_to_stock"] == ORDER_IN_STOCK:
            return []
        touched = []
        ts = order["order_ts"] or now()
        for it in self.order_items(order_id):
            pn = (it["part_number"] or "").strip()
            if not pn:
                continue
            part = self.find_part(pn)
            if part:
                pid = part["id"]
                self.conn.execute(
                    "UPDATE parts SET unit_price=COALESCE(NULLIF(?,0), unit_price), "
                    "description=COALESCE(NULLIF(description,''), ?), "
                    "purchase_link=COALESCE(NULLIF(purchase_link,''), ?) WHERE id=?",
                    (it["unit_price"] or 0, it["description"], it["link"] or SUPPLIER_LION, pid))
            else:
                cur = self.conn.execute(
                    "INSERT INTO parts(part_number, description, quantity, min_quantity, unit_price, purchase_link, "
                    "created_at, updated_at) VALUES(?,?,0,0,?,?,?,?)",
                    (pn, it["description"], it["unit_price"] or 0, it["link"] or SUPPLIER_LION, now(), now()))
                pid = cur.lastrowid
            if it["unit_price"]:
                self.add_price(pid, it["unit_price"], "lion", order["order_code"], ts)
            self.change_stock(pid, int(it["quantity"] or 0), f"سفارش لیون {order['order_code']}", "lion", commit=False)
            # از لیست خرید خط بخورد
            self.conn.execute("DELETE FROM shopping WHERE part_number=? COLLATE NOCASE", (pn,))
            touched.append(pid)
        self.conn.execute("UPDATE lion_orders SET added_to_stock=1 WHERE id=?", (order_id,))
        self.conn.commit()
        return touched

    def remove_order_from_stock(self, order_id):
        order = self.get_order(order_id)
        if not order or order["added_to_stock"] != ORDER_IN_STOCK:
            return 0
        count = 0
        for it in self.order_items(order_id):
            part = self.find_part(it["part_number"] or "")
            if part:
                self.change_stock(part["id"], -int(it["quantity"] or 0),
                                  f"لغو ورود سفارش لیون {order['order_code']}", "lion", commit=False)
                self.conn.execute("DELETE FROM price_history WHERE part_id=? AND source='lion' AND ref=?",
                                  (part["id"], order["order_code"]))
                count += 1
        self.conn.execute("UPDATE lion_orders SET added_to_stock=0 WHERE id=?", (order_id,))
        self.conn.commit()
        return count

    # ================================================================ projects / BOM
    def list_projects(self):
        return self.q("SELECT p.*, (SELECT COUNT(*) FROM bom_items b WHERE b.project_id=p.id) AS item_count "
                      "FROM projects p ORDER BY p.id DESC")

    def save_project(self, name, description="", project_id=None):
        if project_id:
            self.conn.execute("UPDATE projects SET name=?, description=? WHERE id=?", (name, description, project_id))
        else:
            project_id = self.conn.execute("INSERT INTO projects(name, description, created_at) VALUES(?,?,?)",
                                           (name, description, now())).lastrowid
        self.conn.commit()
        return project_id

    def delete_project(self, project_id):
        self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self.conn.commit()

    def bom(self, project_id):
        """اقلام BOM همراه با وضعیت انبار."""
        return self.q(
            "SELECT b.*, p.id AS part_id, p.quantity AS stock, p.description AS part_desc, p.unit_price, "
            "p.location, p.purchase_link FROM bom_items b "
            "LEFT JOIN parts p ON p.part_number = b.part_number COLLATE NOCASE "
            "WHERE b.project_id=? ORDER BY b.id", (project_id,))

    def add_bom_item(self, project_id, part_number, quantity, designators="", note=""):
        row = self.q1("SELECT id FROM bom_items WHERE project_id=? AND part_number=? COLLATE NOCASE",
                      (project_id, part_number))
        if row:
            self.conn.execute("UPDATE bom_items SET quantity=quantity+?, designators=TRIM(COALESCE(designators,'')||' '||?) "
                              "WHERE id=?", (quantity, designators or "", row["id"]))
        else:
            self.conn.execute("INSERT INTO bom_items(project_id, part_number, quantity, designators, note) VALUES(?,?,?,?,?)",
                              (project_id, part_number.strip(), quantity, designators, note))
        self.conn.commit()

    def update_bom_item(self, item_id, **fields):
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE bom_items SET {sets} WHERE id=?", list(fields.values()) + [item_id])
        self.conn.commit()

    def delete_bom_items(self, ids):
        self.conn.executemany("DELETE FROM bom_items WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    def build_project(self, project_id, boards):
        project = self.q1("SELECT * FROM projects WHERE id=?", (project_id,))
        for b in self.bom(project_id):
            if b["part_id"]:
                self.change_stock(b["part_id"], -b["quantity"] * boards,
                                  f"ساخت {boards} عدد «{project['name']}»", "project", commit=False)
        self.conn.commit()

    # ================================================================ shopping list
    def shopping_list(self):
        return self.q(
            "SELECT s.*, p.id AS part_id, p.quantity AS stock, p.min_quantity, p.description, p.unit_price, "
            "p.purchase_link, p.lion_moq FROM shopping s LEFT JOIN parts p ON p.part_number = s.part_number COLLATE NOCASE "
            "ORDER BY s.id DESC")

    def add_shopping(self, part_number, quantity, source="دستی", note=""):
        row = self.q1("SELECT id, quantity FROM shopping WHERE part_number=? COLLATE NOCASE", (part_number,))
        if row:
            self.conn.execute("UPDATE shopping SET quantity=MAX(quantity, ?), source=? WHERE id=?",
                              (quantity, source, row["id"]))
        else:
            self.conn.execute("INSERT INTO shopping(part_number, quantity, note, source, created_at) VALUES(?,?,?,?,?)",
                              (part_number.strip(), quantity, note, source, now()))
        self.conn.commit()

    def update_shopping(self, item_id, **fields):
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE shopping SET {sets} WHERE id=?", list(fields.values()) + [item_id])
        self.conn.commit()

    def delete_shopping(self, ids):
        self.conn.executemany("DELETE FROM shopping WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    def low_stock_parts(self):
        return self.q("SELECT * FROM parts WHERE min_quantity > 0 AND quantity < min_quantity")

    # ================================================================ statistics
    def monthly_purchases(self, months=12):
        """[(jalali 'YYYY/MM', total rial)] برای سفارش‌های لیون."""
        totals = {}
        for o in self.q("SELECT order_date, total FROM lion_orders"):
            m = re.match(r"(\d{4})/(\d{1,2})", o["order_date"] or "")
            if m:
                key = f"{m.group(1)}/{int(m.group(2)):02d}"
                totals[key] = totals.get(key, 0) + money(o["total"])
        today = jdatetime.date.today()
        out, y, mo = [], today.year, today.month
        for _ in range(months):
            key = f"{y}/{mo:02d}"
            out.append((key, totals.get(key, 0)))
            mo -= 1
            if mo == 0:
                y, mo = y - 1, 12
        return list(reversed(out))

    def monthly_inflow(self, months=12):
        """[(jalali 'YYYY/MM', ارزش ریالی ورودی‌ها)] از تراکنش‌های ورود (به‌جز موجودی اولیه)."""
        totals = {}
        for t in self.q("SELECT t.change, t.created_at, p.unit_price FROM transactions t JOIN parts p ON p.id=t.part_id "
                        "WHERE t.change > 0 AND COALESCE(t.reason,'') != 'موجودی اولیه' AND t.source != 'import'"):
            j = to_jalali(t["created_at"], False)
            if j:
                key = j[:7]
                totals[key] = totals.get(key, 0) + t["change"] * (t["unit_price"] or 0)
        today = jdatetime.date.today()
        out, y, mo = [], today.year, today.month
        for _ in range(months):
            key = f"{y}/{mo:02d}"
            out.append((key, totals.get(key, 0)))
            mo -= 1
            if mo == 0:
                y, mo = y - 1, 12
        return list(reversed(out))

    def value_by_top_category(self):
        cats = self.categories()
        res = {}
        for p in self.q("SELECT category_id, MAX(quantity,0)*unit_price AS v, quantity FROM parts"):
            top = cats[p["category_id"]]["top"] if p["category_id"] in cats else "بدون دسته"
            v = res.setdefault(top, [0, 0])
            v[0] += p["v"] or 0
            v[1] += 1
        return sorted(((k, v[0], v[1]) for k, v in res.items()), key=lambda x: -x[1])

    def top_consumed(self, days=365, limit=10):
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self.q(
            "SELECT p.part_number, p.description, -SUM(t.change) AS used FROM transactions t JOIN parts p ON p.id=t.part_id "
            "WHERE t.change < 0 AND t.source != 'lion' AND t.created_at >= ? GROUP BY t.part_id ORDER BY used DESC LIMIT ?",
            (since, limit))

    def top_value(self, limit=10):
        return self.q("SELECT part_number, description, quantity, unit_price, MAX(quantity,0)*unit_price AS value "
                      "FROM parts ORDER BY value DESC LIMIT ?", (limit,))

    def order_totals(self):
        rows = self.q("SELECT total FROM lion_orders")
        return len(rows), sum(money(r["total"]) for r in rows)

    def movement_since(self, days=30):
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = self.q1("SELECT COALESCE(SUM(CASE WHEN change>0 THEN change END),0) AS inn, "
                    "COALESCE(-SUM(CASE WHEN change<0 THEN change END),0) AS outt FROM transactions WHERE created_at >= ?",
                    (since,))
        return r["inn"], r["outt"]
