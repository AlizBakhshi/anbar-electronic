"""خواندن فایل اکسل/CSV و حدس زدن ستون‌ها (برای ایمپورت قطعه‌ها و BOM)."""
import csv
import os
import re

PART_FIELDS = [
    ("part_number", "پارت نامبر", True),
    ("quantity", "موجودی", False),
    ("description", "توضیحات", False),
    ("location", "محل نگهداری", False),
    ("package", "پکیج", False),
    ("manufacturer", "سازنده", False),
    ("min_quantity", "حداقل موجودی", False),
    ("unit_price", "قیمت واحد", False),
    ("purchase_link", "لینک خرید", False),
]

BOM_FIELDS = [
    ("part_number", "پارت نامبر / مقدار", True),
    ("quantity", "تعداد در هر برد", False),
    ("designators", "Designator / مرجع", False),
    ("note", "یادداشت", False),
]

KEYWORDS = {
    "part_number": ["manufacturer part", "mfr part", "mpn", "part number", "part no", "partnumber", "p/n", "pn",
                    "پارت", "شماره قطعه", "کد قطعه", "part", "value", "مقدار"],
    "quantity": ["quantity", "qty", "تعداد", "موجودی", "count", "stock"],
    "description": ["description", "desc", "توضیح", "comment", "شرح", "name", "نام"],
    "location": ["location", "محل", "قفسه", "bin", "box", "جعبه"],
    "package": ["package", "footprint", "case", "پکیج"],
    "manufacturer": ["manufacturer", "mfr", "brand", "سازنده", "برند"],
    "min_quantity": ["min", "حداقل"],
    "unit_price": ["unit price", "price", "قیمت", "فی"],
    "purchase_link": ["link", "url", "لینک", "supplier"],
    "designators": ["designator", "reference", "refdes", "ref", "مرجع"],
    "note": ["note", "یادداشت", "comment"],
}


def read_table(path):
    """(headers, rows) — ردیف اولی که حداقل دو خانه‌ی پر دارد، سرستون در نظر گرفته می‌شود."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        raw = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        data = None
        for enc in ("utf-8-sig", "cp1256", "latin-1"):
            try:
                with open(path, encoding=enc, newline="") as f:
                    data = f.read()
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(data[:4000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        raw = list(csv.reader(data.splitlines(), dialect))
    raw = [r for r in raw if any(str(c or "").strip() for c in r)]
    if not raw:
        return [], []
    h = next((i for i, r in enumerate(raw[:20]) if sum(1 for c in r if str(c or "").strip()) >= 2), 0)
    headers = [str(c or "").strip() for c in raw[h]]
    rows = [[("" if c is None else c) for c in r] for r in raw[h + 1:]]
    return headers, rows


def guess_mapping(headers, fields):
    """{field_key: column_index}"""
    out, used = {}, set()
    norm = [re.sub(r"\s+", " ", (h or "").lower()) for h in headers]
    for key, _, _ in fields:
        for kw in KEYWORDS.get(key, []):
            hit = next((i for i, h in enumerate(norm) if i not in used and kw in h), None)
            if hit is not None:
                out[key] = hit
                used.add(hit)
                break
    return out


def cell(row, mapping, key, default=""):
    i = mapping.get(key)
    if i is None or i >= len(row):
        return default
    v = row[i]
    return default if v is None else str(v).strip()


def to_int(text, default=0):
    m = re.search(r"-?\d+", str(text or "").replace(",", ""))
    return int(m.group()) if m else default


def to_float(text, default=0.0):
    m = re.search(r"-?\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(m.group()) if m else default


def count_designators(text):
    parts = [p for p in re.split(r"[,\s;]+", text or "") if p]
    return len(parts)
