import re
import sqlite3
import os
import secrets
import hashlib
import hmac

class curdCommands:
    def __init__(self, Datas):
        self.Datas = Datas
        self.db_path = Datas.database  # مسیر فایل دیتابیس SQLite
        
        # اطمینان از وجود دایرکتوری دیتابیس
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
    def _get_connection(self):
        """ایجاد و بازگرداندن اتصال به دیتابیس SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            # فعال کردن foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            return conn
        except sqlite3.Error as e:
            print(f"خطا در اتصال به دیتابیس: {e}")
            raise
    
    def cTable_admins(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = "CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT, chatid INTEGER UNIQUE)"
            cur.execute(command)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating admins table: {e}")

    def cTable_tokens(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone INTEGER NOT NULL,
                    token TEXT NOT NULL
                )
            """)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating tokens table: {e}")

    def cTable_jobs(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = "CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, chatid INTEGER UNIQUE, jobid TEXT)"
            cur.execute(command)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating jobs table: {e}")

    def insert_tokens_by_phone(self, phone, tokens):
        print(phone)
        print(tokens)
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            # ادغام با توکن‌های قبلی همان شماره + یک ردیف برای هر phone (بدون تکرار ردیف)
            cur.execute("SELECT token FROM tokens WHERE phone = ?", (phone,))
            rows = cur.fetchall()
            existing_parts = []
            for row in rows:
                if row and row[0]:
                    existing_parts.extend([t for t in str(row[0]).split(",") if t])
            merged = []
            seen = set()
            for t in existing_parts + list(tokens):
                if t and t not in seen:
                    seen.add(t)
                    merged.append(t)
            cur.execute("DELETE FROM tokens WHERE phone = ?", (phone,))
            tokens_combined = ",".join(merged)
            sql_insert = "INSERT INTO tokens (phone, token) VALUES (?, ?)"
            cur.execute(sql_insert, (phone, tokens_combined))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error inserting tokens: {e}")

    def check_tokens_by_phone(self, phone):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tokens WHERE phone = ?", (phone,))
            exists = cur.fetchone()[0]
            cur.close()
            conn.close()
            
            if exists > 0:
                return 0  # توکن‌هایی برای شماره تلفن وجود دارد
            else:
                return 1  # توکن‌هایی برای شماره تلفن وجود ندارد
        except Exception as e:
            print(f"Error checking tokens: {e}")
            return -1

    def delete_tokens_by_phone(self, phone):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            sql_delete = "DELETE FROM tokens WHERE phone = ?"
            cur.execute(sql_delete, (phone,))
            conn.commit()
            print(f"{cur.rowcount} توکن برای شماره {phone} حذف شد.")
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error deleting tokens: {e}")

    def get_tokens_by_phone(self, phone):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            sql_select = "SELECT token FROM tokens WHERE phone = ?"
            cur.execute(sql_select, (phone,))
            tokens = cur.fetchall()
            
            if not tokens:
                cur.close()
                conn.close()
                return []
            
            token_list = tokens[0][0].split(',')
            cur.close()
            conn.close()
            return token_list
        except Exception as e:
            print(f"Error retrieving tokens: {e}")
            return []

    def addJob(self, chatid, job):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "INSERT OR REPLACE INTO jobs (chatid, jobid) VALUES (?, ?)"
            cur.execute(insrt, (chatid, job))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error adding job: {e}")
            return 0

    def removeJob(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "DELETE FROM jobs WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error removing job: {e}")
            return 0

    def getJob(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT jobid FROM jobs WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            data = cur.fetchone()
            cur.close()
            conn.close()
            if data:
                return data[0]
            else:
                return None
        except Exception as e:
            print(f"Error getting job: {e}")
            return None

    def setAdmin(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "INSERT OR IGNORE INTO admins (chatid) VALUES (?)"
            cur.execute(insrt, (chatid,))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error setting admin: {e}")
            return 0

    def getAdmins(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT chatid FROM admins"
            cur.execute(insrt)
            admin_chatids = [row[0] for row in cur.fetchall()]
            cur.close()
            conn.close()
            return admin_chatids
        except Exception as e:
            print(f"Error getting admins: {e}")
            return []

    def remAdmin(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "DELETE FROM admins WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error removing admin: {e}")
            return 0

    def cTable_sents(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = "CREATE TABLE IF NOT EXISTS sents(id INTEGER PRIMARY KEY AUTOINCREMENT, chatid INTEGER, token TEXT UNIQUE, status TEXT)"
            cur.execute(command)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating sents table: {e}")

    def cTable_adminp(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = (
                "CREATE TABLE IF NOT EXISTS adminp("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "chatid INTEGER UNIQUE, "
                "slogin INTEGER, "
                "slimit INTEGER, "
                "scode INTEGER"
                ")"
            )
            cur.execute(command)

            # اطمینان از وجود ستون ssearch برای مدیریت حالت جستجو در دیوار
            # در SQLite امکان IF NOT EXISTS برای ستون نیست، پس در یک try/except انجام می‌دهیم
            try:
                cur.execute("ALTER TABLE adminp ADD COLUMN ssearch INTEGER DEFAULT 0")
                conn.commit()
            except Exception as e:
                # اگر ستون از قبل وجود داشته باشد، خطا را نادیده می‌گیریم
                # سایر خطاها فقط لاگ می‌شوند تا جدول خراب نشود
                msg = str(e)
                if "duplicate column name" not in msg.lower():
                    print(f"Warning while ensuring ssearch column in adminp: {e}")

            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating adminp table: {e}")

    def addAdmin(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "INSERT OR IGNORE INTO adminp (chatid, slogin, slimit, scode) VALUES (?, ?, ?, ?)"
            cur.execute(insrt, (chatid, 0, 0, 0))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error adding admin: {e}")
            return 0

    def _logins_table_sql_new(self) -> str:
        """یک شماره می‌تواند در چند پنل (chatid) مجزا لاگین شود — یکتایی فقط روی (chatid, phone)."""
        return """
            CREATE TABLE logins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chatid INTEGER NOT NULL,
                phone INTEGER NOT NULL,
                cookie TEXT,
                active INTEGER,
                used INTEGER,
                UNIQUE(chatid, phone)
            )
        """

    def cTable_logins(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='logins'")
            row = cur.fetchone()
            if row and row[0] and (
                re.search(r"phone\s+INTEGER\s+UNIQUE", row[0], re.I)
                or re.search(r"phone\s+INTEGER\s+NOT\s+NULL\s+UNIQUE", row[0], re.I)
            ):
                cur.execute("ALTER TABLE logins RENAME TO logins_legacy_phone_unique")
                cur.execute(self._logins_table_sql_new())
                cur.execute(
                    """
                    INSERT INTO logins (id, chatid, phone, cookie, active, used)
                    SELECT id, chatid, phone, cookie, active, used FROM logins_legacy_phone_unique
                    """
                )
                cur.execute("DROP TABLE logins_legacy_phone_unique")
                conn.commit()
                print("✅ جدول logins: یکتایی از «فقط phone» به «(chatid, phone)» مهاجرت داده شد.")
            else:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS logins ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "chatid INTEGER NOT NULL, "
                    "phone INTEGER NOT NULL, "
                    "cookie TEXT, "
                    "active INTEGER, "
                    "used INTEGER, "
                    "UNIQUE(chatid, phone)"
                    ")"
                )
                conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating logins table: {e}")

    def cTable_manage(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = "CREATE TABLE IF NOT EXISTS manage(id INTEGER PRIMARY KEY AUTOINCREMENT, chatid INTEGER UNIQUE, active INTEGER, limite INTEGER, climit INTEGER, nardeban_type INTEGER, last_round_robin_phone INTEGER, interval_minutes INTEGER, stop_hour INTEGER, cost_priority_1 INTEGER, cost_priority_2 INTEGER, natural_flow_min_minutes INTEGER DEFAULT 3, natural_flow_max_minutes INTEGER DEFAULT 15)"
            cur.execute(command)
            # اضافه کردن ستون nardeban_type به جدول موجود (اگر وجود نداشته باشد)
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN nardeban_type INTEGER DEFAULT 1")
                conn.commit()
            except:
                pass  # ستون قبلاً وجود دارد
            # اضافه کردن ستون last_round_robin_phone برای ردیابی آخرین لاگین استفاده شده در نوع نوبتی
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN last_round_robin_phone INTEGER")
                conn.commit()
            except:
                pass  # ستون قبلاً وجود دارد
            # اضافه کردن ستون interval_minutes برای تنظیم فاصله بین نردبان‌ها
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN interval_minutes INTEGER DEFAULT 5")
                conn.commit()
            except:
                pass  # ستون قبلاً وجود دارد
            # اضافه کردن ستون stop_hour برای ذخیره ساعت توقف خودکار
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN stop_hour INTEGER")
                conn.commit()
            except:
                pass  # ستون قبلاً وجود دارد
            # اولویت پلن هزینه 1
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN cost_priority_1 INTEGER")
                conn.commit()
            except:
                pass
            # اولویت پلن هزینه 2
            try:
                cur.execute("ALTER TABLE manage ADD COLUMN cost_priority_2 INTEGER")
                conn.commit()
            except:
                pass
            try:
                cur.execute(
                    "ALTER TABLE manage ADD COLUMN natural_flow_min_minutes INTEGER DEFAULT 3"
                )
                conn.commit()
            except Exception:
                pass
            try:
                cur.execute(
                    "ALTER TABLE manage ADD COLUMN natural_flow_max_minutes INTEGER DEFAULT 15"
                )
                conn.commit()
            except Exception:
                pass
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating manage table: {e}")

    def cTable_web_commands(self):
        """ایجاد جدول صف فرمان‌های پنل وب"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = """
                CREATE TABLE IF NOT EXISTS web_commands(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chatid INTEGER NOT NULL,
                    command_type TEXT NOT NULL,
                    payload TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    processed_at TEXT
                )
            """
            cur.execute(command)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating web_commands table: {e}")

    def cTable_web_panel_auth(self):
        """رمز ورود پنل وب به‌ازای هر ادمین (شناسهٔ چت بله)"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS web_panel_auth(
                    chatid INTEGER PRIMARY KEY,
                    pass_hash TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    pass_plain TEXT
                )
                """
            )
            try:
                cur.execute("ALTER TABLE web_panel_auth ADD COLUMN pass_plain TEXT")
                conn.commit()
            except Exception:
                pass
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating web_panel_auth table: {e}")

    _PWEB_ITER = 120_000

    @staticmethod
    def _normalize_phone_digits(raw):
        if raw is None:
            return ""
        text = str(raw).strip()
        trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        text = text.translate(trans).replace(" ", "").replace("-", "")
        if text.startswith("+98"):
            text = "0" + text[3:]
        elif text.startswith("98") and len(text) >= 12:
            text = "0" + text[2:]
        elif len(text) == 10 and text.startswith("9") and text.isdigit():
            text = "0" + text
        return text

    def _hash_panel_password(self, plain: str) -> str:
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            salt,
            self._PWEB_ITER,
            dklen=32,
        )
        return f"v1:{salt.hex()}:{dk.hex()}"

    def _verify_panel_pass_hash(self, stored: str, plain: str) -> bool:
        if not stored or not plain:
            return False
        parts = str(stored).split(":")
        if len(parts) != 3 or parts[0] != "v1":
            return False
        try:
            salt = bytes.fromhex(parts[1])
            expected = bytes.fromhex(parts[2])
        except Exception:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            salt,
            self._PWEB_ITER,
            dklen=len(expected),
        )
        return hmac.compare_digest(dk, expected)

    def find_chatid_by_login_phone(self, phone_normalized: str) -> int | None:
        """اولین chatid که این شماره در logins دارد (بعد از نرمال‌سازی)."""
        norm = self._normalize_phone_digits(phone_normalized)
        if not norm:
            return None
        variants = {norm}
        if norm.startswith("0") and len(norm) == 11:
            variants.add(norm[1:])
        try:
            variants.add(str(int(norm)))
        except Exception:
            pass
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT chatid, phone FROM logins")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            for chatid, ph in rows:
                dbn = self._normalize_phone_digits(ph)
                if not dbn:
                    continue
                db_vars = {dbn}
                if dbn.startswith("0") and len(dbn) == 11:
                    db_vars.add(dbn[1:])
                try:
                    db_vars.add(str(int(dbn)))
                except Exception:
                    pass
                if variants & db_vars:
                    return int(chatid)
            return None
        except Exception as e:
            print(f"Error find_chatid_by_login_phone: {e}")
            return None

    def issue_web_panel_password(self, chatid: int) -> str:
        """تولید رمز تصادفی، ذخیرهٔ هش، بازگرداندن رمز به‌صورت یک‌بار خواندنی."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        plain = "".join(secrets.choice(alphabet) for _ in range(10))
        ph = self._hash_panel_password(plain)
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO web_panel_auth (chatid, pass_hash, pass_plain, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chatid) DO UPDATE SET
                    pass_hash = excluded.pass_hash,
                    pass_plain = excluded.pass_plain,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (int(chatid), ph, plain),
            )
            conn.commit()
            cur.close()
            conn.close()
            return plain
        except Exception as e:
            print(f"Error issue_web_panel_password: {e}")
            raise

    def verify_web_panel_password(self, chatid: int, plain: str) -> bool:
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT pass_hash FROM web_panel_auth WHERE chatid = ?", (int(chatid),))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row or not row[0]:
                return False
            return self._verify_panel_pass_hash(row[0], plain)
        except Exception as e:
            print(f"Error verify_web_panel_password: {e}")
            return False

    def has_web_panel_password(self, chatid: int) -> bool:
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM web_panel_auth WHERE chatid = ? AND pass_hash IS NOT NULL AND TRIM(pass_hash) != ''", (int(chatid),))
            ok = cur.fetchone() is not None
            cur.close()
            conn.close()
            return ok
        except Exception as e:
            print(f"Error has_web_panel_password: {e}")
            return False

    def get_web_panel_pass_plain(self, chatid: int) -> str | None:
        """متن رمز ذخیره‌شده برای نمایش مجدد در ربات (بدون صدور مجدد). قابل بازیابی نیست اگر قبلاً فقط هش ثبت شده باشد."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT pass_plain FROM web_panel_auth WHERE chatid = ?",
                (int(chatid),),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row or row[0] is None:
                return None
            t = str(row[0]).strip()
            return t if t else None
        except Exception as e:
            print(f"Error get_web_panel_pass_plain: {e}")
            return None

    def addManage(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "INSERT OR IGNORE INTO manage (chatid, active, limite, climit, nardeban_type, last_round_robin_phone, interval_minutes, stop_hour, cost_priority_1, cost_priority_2, natural_flow_min_minutes, natural_flow_max_minutes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            cur.execute(insrt, (chatid, 0, 100, 0, 1, None, 5, None, None, None, 3, 15))  # 1 = ترتیبی کامل هر لاگین (پیش‌فرض), 5 = فاصله پیش‌فرض 5 دقیقه
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error adding manage: {e}")
            return 0

    def addLogin(self, chatid, phone, cookie):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cid, ph = int(chatid), int(phone)
            cur.execute("SELECT 1 FROM logins WHERE chatid = ? AND phone = ?", (cid, ph))
            existed = cur.fetchone() is not None
            cur.execute(
                """
                INSERT INTO logins (chatid, phone, cookie, active, used)
                VALUES (?, ?, ?, 1, 0)
                ON CONFLICT(chatid, phone) DO UPDATE SET
                    cookie = excluded.cookie,
                    active = 1
                """,
                (cid, ph, cookie),
            )
            conn.commit()
            cur.close()
            conn.close()
            return 0 if existed else 1
        except Exception as e:
            print(f"error to add login , code : {str(e)}")
            return 0

    def delLogin(self, phone, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "DELETE FROM logins WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (phone, int(chatid)))
            conn.commit()
            ok = cur.rowcount > 0
            cur.close()
            conn.close()
            return 1 if ok else 0
        except Exception as e:
            print(e)
            return 0

    def delLoginByChatid(self, phone, chatid):
        """حذف لاگین فقط برای یک chatid خاص (ایمن‌تر برای پنل وب)"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "DELETE FROM logins WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (phone, int(chatid)))
            conn.commit()
            affected = cur.rowcount
            cur.close()
            conn.close()
            return affected > 0
        except Exception as e:
            print(f"Error deleting login by chatid: {e}")
            return False

    def setStatus(self, q, v, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            # استفاده از f-string برای نام ستون (امن است چون از داخل کنترل می‌شود)
            insrt = f"UPDATE adminp SET {q} = ? WHERE chatid = ?"
            cur.execute(insrt, (v, chatid))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(e)
            return 0

    def setStatusManage(self, q, v, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = f"UPDATE manage SET {q} = ? WHERE chatid = ?"
            cur.execute(insrt, (v, chatid))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(e)
            return 0

    def getStatusByQ(self, q, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = f"SELECT {q} FROM adminp WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                return result[0]
            return 0
        except Exception as e:
            print(e)
            return 0

    def get_phone_numbers_by_chatid(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            command = "SELECT phone FROM logins WHERE chatid = ?"
            cur.execute(command, (chatid,))
            phone_numbers = cur.fetchall()
            cur.close()
            conn.close()
            return [phone[0] for phone in phone_numbers]
        except Exception as e:
            print(f"Error getting phone numbers: {e}")
            return []

    def getStatus(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT slogin, slimit, scode FROM adminp WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                return result
            return (0, 0, 0)
        except Exception as e:
            print(e)
            return (0, 0, 0)

    def updateLogin(self, phone, cookie, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE logins SET cookie = ?, active = 1 WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (cookie, phone, int(chatid)))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error updating login: {e}")
            return 0

    def refreshUsed(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE logins SET used = ? WHERE chatid = ?"
            cur.execute(insrt, (0, chatid))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error in refresh used, error : {str(e)}")
            return 0

    def updateLimitLogin(self, phone, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE logins SET used = used + ? WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (1, phone, int(chatid)))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error updating limit login: {e}")
            return 0

    def getLimitLogin(self, phone, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT used FROM logins WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (phone, int(chatid)))
            data = cur.fetchone()
            cur.close()
            conn.close()
            if data:
                return data[0]
            else:
                return 0
        except Exception as e:
            print(f"Error getting limit login: {e}")
            return 0

    def reset_nardeban_count(self, phone, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE logins SET used = ? WHERE phone = ? AND chatid = ?"
            cur.execute(insrt, (0, phone, int(chatid)))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error resetting nardeban count: {e}")
            return 0

    def activeLogin(self, phone, status, chatid=None):
        """
        فعال یا غیرفعال کردن یک لاگین.
        خروجی: (موفقیت, پیام)
        """
        conn = None
        cur = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()

            # نرمال‌سازی ورودی شماره
            phone_candidates = []
            if phone is not None:
                phone_str = str(phone).strip()
                if phone_str:
                    phone_candidates.append(phone_str)
                    digits_only = "".join(ch for ch in phone_str if ch.isdigit())
                    if digits_only and digits_only not in phone_candidates:
                        phone_candidates.append(digits_only)
                    try:
                        phone_int = int(digits_only or phone_str)
                        if phone_int not in phone_candidates:
                            phone_candidates.append(phone_int)
                    except Exception:
                        pass

            if not phone_candidates:
                phone_candidates = [phone]

            updated = 0
            matched_value = None
            status_val = 1 if int(status) == 1 else 0

            for value in phone_candidates:
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                query = "UPDATE logins SET active = ? WHERE phone = ?"
                params = [status_val, value]
                if chatid is not None:
                    query += " AND chatid = ?"
                    params.append(int(chatid))
                cur.execute(query, tuple(params))
                if cur.rowcount > 0:
                    updated = cur.rowcount
                    matched_value = value
                    break

            conn.commit()

            if updated > 0:
                state_txt = "فعال" if status_val == 1 else "غیرفعال"
                display_phone = matched_value if matched_value is not None else phone
                return True, f"شماره {display_phone} {state_txt} شد."
            else:
                return False, "شماره‌ای با این مشخصات در لیست شما یافت نشد."
        except Exception as e:
            print(f"Error activating login: {e}")
            return False, "خطا در به‌روزرسانی وضعیت شماره."
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def addSent(self, chatid, token, status):
        """افزودن توکن نردبان شده به دیتابیس - برمی‌گرداند 1 اگر جدید بود، 0 اگر قبلاً وجود داشت"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # چک کردن اینکه آیا توکن قبلاً وجود دارد یا نه
            check_sql = "SELECT id FROM sents WHERE chatid = ? AND token = ?"
            cur.execute(check_sql, (chatid, token))
            existing = cur.fetchone()
            
            if existing:
                # توکن قبلاً وجود دارد
                cur.close()
                conn.close()
                return 0
            
            # توکن جدید است، اضافه می‌کنیم
            insrt = "INSERT INTO sents (chatid, token, status) VALUES (?, ?, ?)"
            cur.execute(insrt, (chatid, token, status))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error adding sent: {e}")
            return 0

    def getCookies(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT phone, cookie, used FROM logins WHERE active = ? AND chatid = ?"
            cur.execute(insrt, (1, chatid))
            data = cur.fetchall()
            cur.close()
            conn.close()
            if data:
                return data
            else:
                return None
        except Exception as e:
            print(f"Error getting cookies: {e}")
            return None

    def getLogins(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT phone, cookie, active FROM logins WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            data = cur.fetchall()
            cur.close()
            conn.close()
            if data:
                return data
            else:
                return 0
        except Exception as e:
            print(f"Error getting logins: {e}")
            return 0

    def getStatusBot(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT active FROM manage WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            data = cur.fetchone()
            cur.close()
            conn.close()
            if data:
                return data[0]
            else:
                return 0
        except Exception as e:
            print(f"Error getting status bot: {e}")
            return 0

    def getManage(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "SELECT active, limite, climit, nardeban_type, last_round_robin_phone, interval_minutes, stop_hour, cost_priority_1, cost_priority_2, natural_flow_min_minutes, natural_flow_max_minutes FROM manage WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            data = cur.fetchone()
            cur.close()
            conn.close()
            if data:
                row = list(data)
                while len(row) < 11:
                    row.append(None)
                if len(row) >= 6 and row[5] is None:
                    row[5] = 5
                return tuple(row[:11])
            else:
                # پیش‌فرض: ترتیبی کامل، فاصله ۵ دقیقه؛ بازهٔ جریان طبیعی ۳–۱۵ از natural_flow helper
                return (0, 100, 0, 1, None, 5, None, None, None, None, None)
        except Exception as e:
            print(f"Error getting manage: {e}")
            return (0, 100, 0, 1, None, 5, None, None, None, None, None)

    def editLimit(self, newLimit, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE manage SET limite = ? WHERE chatid = ?"
            cur.execute(insrt, (int(newLimit), chatid))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error editing limit: {e}")
            return 0

    def get_pending_tokens_by_phone(self, phone, chatid):
        """دریافت لیست توکن‌های pending برای یک شماره خاص"""
        try:
            all_tokens = self.get_tokens_by_phone(phone=phone)
            if not all_tokens:
                return []
            
            conn = self._get_connection()
            cur = conn.cursor()
            # دریافت توکن‌های نردبان شده (success)
            placeholders = ','.join(['?' for _ in all_tokens])
            cur.execute(f"SELECT token FROM sents WHERE chatid = ? AND status = ? AND token IN ({placeholders})", 
                       (chatid, "success") + tuple(all_tokens))
            sent_tokens = {row[0] for row in cur.fetchall()}
            cur.close()
            conn.close()
            
            # برگرداندن توکن‌هایی که نردبان نشده‌اند
            pending = [t for t in all_tokens if t and t.strip() and t not in sent_tokens]
            return pending
        except Exception as e:
            print(f"Error getting pending tokens by phone: {e}")
            return []

    def get_all_pending_tokens(self, chatid):
        """دریافت تمام توکن‌های pending از همه لاگین‌ها به صورت لیست (phone, token)"""
        try:
            phone_numbers = self.get_phone_numbers_by_chatid(chatid=chatid)
            all_pending = []
            
            for phone in phone_numbers:
                pending = self.get_pending_tokens_by_phone(phone=phone, chatid=chatid)
                for token in pending:
                    all_pending.append((phone, token))
            
            return all_pending
        except Exception as e:
            print(f"Error getting all pending tokens: {e}")
            return []

    def get_next_pending_token_by_phone(self, phone, chatid):
        """دریافت اولین توکن pending برای یک شماره (برای حالت نوبتی)"""
        pending = self.get_pending_tokens_by_phone(phone=phone, chatid=chatid)
        return pending[0] if pending else None

    def remSents(self, chatid):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "DELETE FROM sents WHERE chatid = ?"
            cur.execute(insrt, (chatid,))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error removing sents: {e}")
            return 0

    def remSents_for_tokens(self, chatid, tokens):
        """حذف رکوردهای sents فقط برای توکن‌های داده‌شده (مثلاً پس از ریست یک لاگین)."""
        if not tokens:
            return 0
        try:
            uniq = [t for t in {str(x).strip() for x in tokens if x and str(x).strip()}]
            if not uniq:
                return 0
            conn = self._get_connection()
            cur = conn.cursor()
            deleted = 0
            batch_size = 400
            for i in range(0, len(uniq), batch_size):
                batch = uniq[i : i + batch_size]
                placeholders = ",".join(["?" for _ in batch])
                sql = f"DELETE FROM sents WHERE chatid = ? AND token IN ({placeholders})"
                cur.execute(sql, (int(chatid),) + tuple(batch))
                deleted += cur.rowcount or 0
            conn.commit()
            cur.close()
            conn.close()
            return deleted
        except Exception as e:
            print(f"Error removing sents for token list: {e}")
            return 0

    def getStats(self, chatid):
        """دریافت آمار اگهی‌ها برای یک chatid (با جزئیات هر لاگین) - استفاده از JSON با ساختار جدید"""
        try:
            from .tokens_manager import get_token_stats, load_tokens_json
            
            # دریافت شماره‌های مربوط به این chatid
            phone_numbers = self.get_phone_numbers_by_chatid(chatid=chatid)
            
            # آمار هر لاگین
            login_stats = []
            total_nardeban = 0
            total_tokens_all = 0
            total_pending = 0
            total_failed = 0
            
            # دریافت توکن‌ها از JSON
            tokens_data = load_tokens_json()
            json_tokens_by_phone = tokens_data.get(chatid, {})
            
            for phone in phone_numbers:
                # دریافت آمار برای این phone از JSON
                phone_stats = get_token_stats(chatid=chatid, phone=phone)
                
                pending_count = phone_stats.get("pending", 0)
                success_count = phone_stats.get("success", 0)
                failed_count = phone_stats.get("failed", 0)
                total_count = phone_stats.get("total", 0)
                
                login_stats.append({
                    'phone': phone,
                    'nardeban_count': success_count,
                    'total_tokens': total_count,
                    'pending_count': pending_count,
                    'failed_count': failed_count
                })
                
                total_nardeban += success_count
                total_tokens_all += total_count
                total_pending += pending_count
                total_failed += failed_count
            
            return {
                'login_stats': login_stats,
                'total_nardeban': total_nardeban,
                'total_tokens': total_tokens_all,
                'total_pending': total_pending,
                'total_failed': total_failed
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            import traceback
            traceback.print_exc()
            return {
                'login_stats': [],
                'total_nardeban': 0,
                'total_tokens': 0,
                'total_pending': 0,
                'total_failed': 0
            }

    def addWebCommand(self, chatid, command_type, payload_json="{}"):
        """افزودن فرمان جدید به صف پنل وب"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "INSERT INTO web_commands (chatid, command_type, payload, status) VALUES (?, ?, ?, 'pending')"
            cur.execute(insrt, (int(chatid), str(command_type), str(payload_json)))
            conn.commit()
            command_id = cur.lastrowid
            cur.close()
            conn.close()
            return command_id
        except Exception as e:
            print(f"Error adding web command: {e}")
            return None

    def getPendingWebCommands(self, limit=20):
        """دریافت فرمان‌های pending برای پردازش توسط worker"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = """
                SELECT id, chatid, command_type, payload, status, created_at
                FROM web_commands
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT ?
            """
            cur.execute(insrt, (int(limit),))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return rows
        except Exception as e:
            print(f"Error getting pending web commands: {e}")
            return []

    def has_web_command_in_flight(self, chatid, command_type):
        """
        آیا برای این چت، startJob (یا نوع دیگر) هنوز در صف یا در حال پردازش معتبر است؟
        ردیف‌های processing خیلی قدیمی نادیده گرفته می‌شوند (مثلاً بعد از کرش worker که
        completeWebCommand صدا زده نشده و UI برای همیشه «در حال شروع» می‌ماند).
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 1 FROM web_commands
                WHERE chatid = ? AND command_type = ?
                  AND (
                    status = 'pending'
                    OR (
                      status = 'processing'
                      AND datetime(created_at) > datetime('now', '-15 minutes')
                    )
                  )
                LIMIT 1
                """,
                (int(chatid), str(command_type)),
            )
            ok = cur.fetchone() is not None
            cur.close()
            conn.close()
            return ok
        except Exception as e:
            print(f"Error has_web_command_in_flight: {e}")
            return False

    def reset_abandoned_processing_web_commands(self):
        """با بالا آمدن worker: ردیف‌های processing مانده از اجرای قبلی را failed می‌کند."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE web_commands
                SET status = 'failed',
                    result = 'پردازش رها شده (worker قبلی متوقف شد؛ در صورت نیاز دوباره بزنید)',
                    processed_at = CURRENT_TIMESTAMP
                WHERE status = 'processing'
                """
            )
            n = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            if n:
                print(f"ℹ️ web_commands: {n} ردیف processing قدیمی به failed تبدیل شد.")
            return n
        except Exception as e:
            print(f"Error reset_abandoned_processing_web_commands: {e}")
            return 0

    def lockWebCommand(self, command_id):
        """قفل نرم فرمان برای جلوگیری از پردازش همزمان"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            insrt = "UPDATE web_commands SET status = 'processing' WHERE id = ? AND status = 'pending'"
            cur.execute(insrt, (int(command_id),))
            conn.commit()
            updated = cur.rowcount
            cur.close()
            conn.close()
            return updated > 0
        except Exception as e:
            print(f"Error locking web command: {e}")
            return False

    def completeWebCommand(self, command_id, success=True, result_text=""):
        """تکمیل فرمان پردازش شده"""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            status = "done" if success else "failed"
            insrt = """
                UPDATE web_commands
                SET status = ?, result = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            cur.execute(insrt, (status, str(result_text), int(command_id)))
            conn.commit()
            cur.close()
            conn.close()
            return 1
        except Exception as e:
            print(f"Error completing web command: {e}")
            return 0

    def getRecentWebCommands(self, limit=50, chatid=None):
        """نمایش آخرین وضعیت فرمان‌ها در پنل؛ در صورت chatid فقط همان ادمین."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            if chatid is not None:
                insrt = """
                    SELECT id, chatid, command_type, payload, status, result, created_at, processed_at
                    FROM web_commands
                    WHERE chatid = ?
                    ORDER BY id DESC
                    LIMIT ?
                """
                cur.execute(insrt, (int(chatid), int(limit)))
            else:
                insrt = """
                    SELECT id, chatid, command_type, payload, status, result, created_at, processed_at
                    FROM web_commands
                    ORDER BY id DESC
                    LIMIT ?
                """
                cur.execute(insrt, (int(limit),))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return rows
        except Exception as e:
            print(f"Error getting recent web commands: {e}")
            return []


def natural_flow_range_minutes_from_manage_row(mng_row):
    """بازهٔ تصادفی جریان طبیعی (دقیقه) از خروجی getManage؛ پیش‌فرض ۳–۱۵."""
    lo, hi = 3, 15
    if mng_row and len(mng_row) > 9 and mng_row[9] is not None:
        try:
            lo = int(mng_row[9])
        except (TypeError, ValueError):
            lo = 3
    if mng_row and len(mng_row) > 10 and mng_row[10] is not None:
        try:
            hi = int(mng_row[10])
        except (TypeError, ValueError):
            hi = 15
    lo = max(1, min(lo, 1440))
    hi = max(1, min(hi, 1440))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


class CreateDB:
    def __init__(self, Datas):
        self.Datas = Datas
        self.db_path = Datas.database
    
    def create(self):
        """ایجاد فایل دیتابیس SQLite (اگر وجود نداشته باشد)"""
        try:
            # SQLite خودکار فایل را ایجاد می‌کند
            conn = sqlite3.connect(self.db_path)
            conn.close()
            print(f"Database file created/verified: {self.db_path}")
        except Exception as e:
            print(f"Error creating database: {e}")
