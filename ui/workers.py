"""کارهای پس‌زمینه (شبکه) تا رابط کاربری هیچ‌وقت قفل نشود."""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

import images
import lion_client as lion
from db import Database, now


class SyncWorker(QThread):
    """ورود به حساب لیون و دریافت سفارش‌های جدید."""
    log = Signal(str)
    need_captcha = Signal(bytes)
    done = Signal(list, str, bool)  # new_order_ids, error, silent

    def __init__(self, user, pwd, silent=False):
        super().__init__()
        self.user, self.pwd, self.silent = user, pwd, silent
        self._captcha_event = threading.Event()
        self._captcha_text = ""

    def provide_captcha(self, text):
        self._captcha_text = text
        self._captcha_event.set()

    def _ask_captcha(self, img):
        self._captcha_event.clear()
        self.need_captcha.emit(img)
        self._captcha_event.wait(300)
        return self._captcha_text

    def run(self):
        db = Database()
        new_ids, error = [], ""
        try:
            client = lion.LionClient(self.user, self.pwd, captcha_callback=self._ask_captcha, log=self.log.emit)
            self.log.emit("در حال ورود به حساب لیون…")
            client.login()
            self.log.emit("در حال خواندن لیست سفارش‌ها…")
            for o in client.fetch_order_list():
                if db.order_exists(o["code"]):
                    db.update_order_info(o)
                    continue
                self.log.emit(f"دریافت جزئیات سفارش {o['code']}…")
                new_ids.append(db.save_order(o, client.fetch_order_items(o)))
        except lion.LoginError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001
            error = f"خطا در ارتباط با سایت: {e}"
        finally:
            db.close()
        self.done.emit(new_ids, error, self.silent)


class EnrichWorker(QThread):
    """تکمیل دسته‌بندی، سازنده، دیتاشیت و پکیج قطعه‌ها از صفحه‌ی محصول لیون."""
    progress = Signal(int, int)
    done = Signal(int, str)

    def __init__(self, part_ids=None, search_missing=True, update_price=False):
        super().__init__()
        self.part_ids = part_ids
        self.search_missing = search_missing
        self.update_price = update_price

    def run(self):
        db = Database()
        updated, error = 0, ""
        try:
            if not db.categories():
                db.upsert_categories(lion.fetch_categories())
            if self.part_ids is None:
                parts = db.parts_to_enrich(only_missing=True)
            else:
                parts = [p for p in (db.get_part(i) for i in self.part_ids) if p]
            total = len(parts)
            self.progress.emit(0, total)
            lock = threading.Lock()

            def job(p):
                url = p["purchase_link"] if "lionelectronic" in (p["purchase_link"] or "") else None
                exact = True
                if not url and self.search_missing:
                    url, exact = lion.search_product(p["part_number"], allow_prefix=True)
                if not url:
                    return p["id"], None
                info = lion.fetch_product_info(url)
                if not exact:
                    # محصول مشابه (مثلاً NE555N برای NE555): فقط دسته‌بندی برداشته شود
                    info = {"categories": info.get("categories"), "category_id": info.get("category_id")}
                elif info.get("image"):
                    try:
                        images.save_thumb(p["id"], info["image"], overwrite=self.update_price)
                    except Exception:  # noqa: BLE001  (عکس اختیاری است)
                        pass
                return p["id"], info

            done = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(job, p) for p in parts]
                for f in as_completed(futures):
                    done += 1
                    try:
                        pid, info = f.result()
                        with lock:
                            if info:
                                info.get("specs", {}).pop("Part Number", None)
                                db.apply_product_info(pid, info, self.update_price)
                                updated += 1
                            else:
                                db.update_part_fields(pid, enriched_at=now())
                    except Exception:  # noqa: BLE001
                        pass
                    self.progress.emit(done, total)
        except Exception as e:  # noqa: BLE001
            error = str(e)
        finally:
            db.close()
        self.done.emit(updated, error)


class CartWorker(QThread):
    """ورود به حساب لیون و افزودن اقلام لیست خرید به سبد خرید سایت."""
    progress = Signal(int, int, str)
    need_captcha = Signal(bytes)
    done = Signal(list, str)  # [(shop_id, part_number, ok, message)], error

    def __init__(self, user, pwd, items):
        """items: [(shop_id, part_number, product_id, quantity, link)]"""
        super().__init__()
        self.user, self.pwd, self.items = user, pwd, items
        self._ev = threading.Event()
        self._cap = ""

    def provide_captcha(self, text):
        self._cap = text
        self._ev.set()

    def _ask(self, img):
        self._ev.clear()
        self.need_captcha.emit(img)
        self._ev.wait(300)
        return self._cap

    def run(self):
        results, error = [], ""
        db = Database()
        try:
            client = lion.LionClient(self.user, self.pwd, captcha_callback=self._ask, log=lambda m: None)
            self.progress.emit(0, len(self.items), "ورود به حساب لیون…")
            client.login()
            before = set()
            try:
                before = client.cart_product_ids()
            except Exception:  # noqa: BLE001
                pass
            sent = []
            for i, (sid, pn, pid, qty, link) in enumerate(self.items, 1):
                self.progress.emit(i - 1, len(self.items), f"افزودن {pn}…")
                part = db.find_part(pn)
                moq = part["lion_moq"] if part and part["lion_moq"] else None
                if moq is None:  # حداقل سفارش هنوز ذخیره نشده: از صفحه‌ی محصول
                    moq = 1
                    try:
                        info = lion.fetch_product_info(link)
                        if info.get("price_tiers"):
                            moq = int(info["price_tiers"][0][0])
                            if part:
                                db.update_part_fields(part["id"], lion_moq=moq)
                    except Exception:  # noqa: BLE001
                        pass
                q = max(int(qty), moq)
                try:
                    ok, msg, _ = client.add_to_cart(pid, q)
                except lion.LoginError:
                    client.login()
                    ok, msg, _ = client.add_to_cart(pid, q)
                note = f"{q} عدد" + (f" (حداقل سفارش لیون {moq} عدد است)" if q != int(qty) else "")
                sent.append([sid, pn, pid, ok, note if ok else msg])
            # بررسی واقعی: سبد خرید سایت را می‌خوانیم
            self.progress.emit(len(self.items), len(self.items), "بررسی سبد خرید…")
            in_cart = None
            try:
                in_cart = client.cart_product_ids()
            except Exception:  # noqa: BLE001
                pass
            for sid, pn, pid, ok, msg in sent:
                if ok and in_cart:  # اگر خواندن سبد ممکن نشد، به پاسخ سایت اعتماد می‌کنیم
                    if pid not in in_cart:
                        ok, msg = False, "سایت قبول نکرد (در سبد دیده نشد)"
                    elif pid in before:
                        msg += " — قبلاً هم در سبد بود؛ تعداد را در سایت بررسی کنید"
                if ok:
                    db.update_shopping(sid, cart_at=now())
                results.append((sid, pn, ok, msg))
        except lion.LoginError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001
            error = f"خطا در ارتباط با سایت: {e}"
        finally:
            db.close()
        self.done.emit(results, error)


class PassiveMatchWorker(QThread):
    """کاتالوگ لیون (در صورت نیاز) + تطبیق پارامتری؛ تطابق‌های دقیق همین‌جا اعمال می‌شوند."""
    progress = Signal(int, int, str)
    done = Signal(int, list, str)   # applied, rows_for_review, error

    def __init__(self, part_ids=None, refresh_catalog=False):
        super().__init__()
        self.part_ids, self.refresh_catalog = part_ids, refresh_catalog

    def run(self):
        import passive_match as pm
        db = Database()
        applied, review, error = 0, [], ""
        try:
            cat = None if self.refresh_catalog else pm.load_catalog(db)
            if not cat:
                cat = pm.crawl_catalog(lambda i, n, m: self.progress.emit(i, n, m))
                pm.save_catalog(db, cat)
            parts = pm.generic_parts(db, self.part_ids)
            pics = []
            for i, (p, spec) in enumerate(parts, 1):
                self.progress.emit(i, len(parts), f"تطبیق {p['part_number']}")
                status, cands = pm.match(spec, cat)
                if status == "exact":
                    pm.apply_match(db, p["id"], cands[0][0], download=False)
                    pics.append((p["id"], cands[0][0]))
                    applied += 1
                else:
                    review.append({"part_id": p["id"], "part_number": p["part_number"], "status": status,
                                   "cands": cands})
            if pics:
                self.progress.emit(0, 0, f"دریافت عکس {len(pics)} قطعه…")
                pm.download_images(pics)
        except Exception as e:  # noqa: BLE001
            error = str(e)
        finally:
            db.close()
        self.done.emit(applied, review, error)


class ImageWorker(QThread):
    """عکس بزرگ‌تر برای نمایش (بدون ذخیره)."""
    done = Signal(bytes)

    def __init__(self, url, size=800):
        super().__init__()
        self.url, self.size = url, size

    def run(self):
        try:
            self.done.emit(images.to_jpeg(images.fetch(self.url, timeout=20), self.size))
        except Exception:  # noqa: BLE001
            self.done.emit(b"")


class CategoriesWorker(QThread):
    done = Signal(int, str)

    def run(self):
        db = Database()
        try:
            cats = lion.fetch_categories()
            db.upsert_categories(cats)
            self.done.emit(len(cats), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(0, str(e))
        finally:
            db.close()
