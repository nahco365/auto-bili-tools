"""SQLite persistence, legacy settings import and administrator credentials."""

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


DEFAULT_SCHEDULES = {
    "Daily": "0 0 15 * * ?", "Manga": "0 0 14 * * ?",
    "MangaPrivilege": "0 0 15 * * ?", "Silver2Coin": "0 0 8 * * ?",
    "Charge": "0 0 12 28 * ?", "VipPrivilege": "0 0 1 * * ?",
    "VipBigPoint": "0 7 1 * * ?", "LiveLottery": "0 0 22 * * ?",
    "LiveFansMedal": "0 5 0 * * ?", "UnfollowBatched": "0 0 6 1 * ?",
}
TASK_SECTIONS = {"Daily": "DailyTaskConfig", "Manga": "MangaTaskConfig",
    "MangaPrivilege": "MangaPrivilegeTaskConfig", "Silver2Coin": "Silver2CoinTaskConfig",
    "Charge": "ChargeTaskConfig", "VipPrivilege": "VipPrivilegeConfig",
    "VipBigPoint": "VipBigPointConfig", "LiveLottery": "LiveLotteryTaskConfig",
    "LiveFansMedal": "LiveFansMedalTaskConfig", "UnfollowBatched": "UnfollowBatchedTaskConfig"}

WEB_DEFAULT_SETTINGS = {
    "Security:RandomSleepMaxMin": "10",
    "Security:IntervalSecondsBetweenRequestApi": "3",
    "LiveLotteryTaskConfig:ExcludeAwardNames": "舰|船|航海|代金券|自拍|照|写真|图|提督",
    "LiveLotteryTaskConfig:DenyUids": "65566781,1277481241,1643654862,603676925",
}


def hash_password(password, salt=None):
    raw_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw_salt, 100_000, 32)
    return base64.b64encode(raw_salt).decode(), base64.b64encode(digest).decode()


def verify_password(password, salt, expected):
    _, digest = hash_password(password, base64.b64decode(salt))
    return hmac.compare_digest(digest, expected)


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS py_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS py_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, position INTEGER NOT NULL,
                uid TEXT NOT NULL, cookie TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS py_accounts_uid ON py_accounts(uid);
            CREATE TABLE IF NOT EXISTS py_schedules (
                task TEXT PRIMARY KEY, cron TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                last_fired TEXT
            );
            CREATE TABLE IF NOT EXISTS py_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL, trigger TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                exit_code INTEGER, output TEXT NOT NULL DEFAULT '', target_uid TEXT
            );
            CREATE INDEX IF NOT EXISTS py_runs_task_time ON py_runs(task, started_at DESC);
            CREATE TABLE IF NOT EXISTS py_task_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                uid TEXT NOT NULL, task TEXT NOT NULL, record_date TEXT NOT NULL,
                trigger TEXT NOT NULL, status TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES py_runs(id)
            );
            CREATE INDEX IF NOT EXISTS py_task_records_day ON py_task_records(record_date,uid,task);
            CREATE TABLE IF NOT EXISTS py_cookie_notifications (
                uid TEXT NOT NULL, sent_date TEXT NOT NULL, PRIMARY KEY(uid,sent_date)
            );
            CREATE TABLE IF NOT EXISTS py_admin (
                id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL
            );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(py_runs)")}
            if "target_uid" not in columns:
                db.execute("ALTER TABLE py_runs ADD COLUMN target_uid TEXT")
            count = db.execute("SELECT count(*) FROM py_settings").fetchone()[0]
            if count == 0 and self._has_table(db, "bili_appsettings"):
                rows = db.execute('SELECT "Key", "Value" FROM bili_appsettings').fetchall()
                db.executemany("INSERT OR IGNORE INTO py_settings(key,value) VALUES(?,?)",
                               [(row[0], row[1] or "") for row in rows])
            db.executemany("INSERT OR IGNORE INTO py_settings(key,value) VALUES(?,?)",
                           list(WEB_DEFAULT_SETTINGS.items()))
            if db.execute("SELECT count(*) FROM py_accounts").fetchone()[0] == 0:
                rows = db.execute("SELECT key,value FROM py_settings WHERE key LIKE 'BiliBiliCookies:%'").fetchall()
                for row in sorted(rows, key=lambda item: int(item[0].split(":")[-1]) if item[0].split(":")[-1].isdigit() else 99999):
                    cookie = row[1]
                    uid = self.cookie_uid(cookie)
                    if uid:
                        db.execute("INSERT OR IGNORE INTO py_accounts(position,uid,cookie,created_at) VALUES(?,?,?,?)",
                                   (len(db.execute("SELECT id FROM py_accounts").fetchall()), uid, cookie, datetime.now().isoformat()))
            if db.execute("SELECT count(*) FROM py_accounts").fetchone()[0] == 0:
                env_cookies = sorted((int(key.rsplit("__", 1)[-1]), value) for key, value in os.environ.items()
                                     if key.lower().startswith("bilibilicookies__") and key.rsplit("__", 1)[-1].isdigit())
                for position, (_, cookie) in enumerate(env_cookies):
                    uid = self.cookie_uid(cookie)
                    if uid:
                        db.execute("INSERT OR IGNORE INTO py_accounts(position,uid,cookie,created_at) VALUES(?,?,?,?)",
                                   (position, uid, cookie, datetime.now().isoformat()))
            migrated_settings = {row[0]: row[1] for row in db.execute("SELECT key,value FROM py_settings")}
            notification_map = {
                "FailureEnabled": "TaskFailureNotification:Enabled",
                "CookieExpiryEnabled": "CookieCheck:NotifyEnabled",
                "TelegramBotToken": "Serilog:WriteTo:3:Args:botToken",
                "TelegramChatId": "Serilog:WriteTo:3:Args:chatId",
                "WorkWeixinWebhook": "Serilog:WriteTo:4:Args:webHookUrl",
                "DingTalkWebhook": "Serilog:WriteTo:5:Args:webHookUrl",
                "ServerChanKey": "Serilog:WriteTo:6:Args:turboScKey",
                "CustomApiUrl": "Serilog:WriteTo:8:Args:api",
                "CustomApiBody": "Serilog:WriteTo:8:Args:bodyJsonTemplate",
                "PushPlusToken": "Serilog:WriteTo:9:Args:token",
                "TeamsWebhook": "Serilog:WriteTo:10:Args:webhook",
                "WorkWeixinCorpId": "Serilog:WriteTo:11:Args:corpId",
                "WorkWeixinAgentId": "Serilog:WriteTo:11:Args:agentId",
                "WorkWeixinSecret": "Serilog:WriteTo:11:Args:secret",
                "WorkWeixinToUser": "Serilog:WriteTo:11:Args:toUser",
                "GotifyUrl": "Serilog:WriteTo:12:Args:host",
                "GotifyToken": "Serilog:WriteTo:12:Args:token",
            }
            for target, source in notification_map.items():
                if source in migrated_settings and "Notification:" + target not in migrated_settings:
                    db.execute("INSERT OR IGNORE INTO py_settings(key,value) VALUES(?,?)",
                               ("Notification:" + target, migrated_settings[source]))
            legacy_crons = {}
            if self._has_table(db, "QRTZ_CRON_TRIGGERS"):
                try:
                    for trigger, expression in db.execute("SELECT TRIGGER_NAME,CRON_EXPRESSION FROM QRTZ_CRON_TRIGGERS"):
                        legacy_crons[trigger] = expression
                except sqlite3.OperationalError:
                    pass
            for task, cron in DEFAULT_SCHEDULES.items():
                section = TASK_SECTIONS[task]
                quartz_cron = next((expression for trigger, expression in legacy_crons.items()
                                    if trigger.endswith(".Cron.Trigger") and f"{task}Job" in trigger), None)
                imported_cron = quartz_cron or migrated_settings.get(section + ":Cron") or cron
                enabled = migrated_settings.get(section + ":IsEnable", "true").lower() == "true"
                db.execute("INSERT OR IGNORE INTO py_schedules(task,cron,enabled) VALUES(?,?,?)",
                           (task, imported_cron, int(enabled)))
            if not db.execute("SELECT id FROM py_admin WHERE id=1").fetchone():
                # Import the .NET password hash when the legacy user table is available.
                if self._has_table(db, "bili_user"):
                    try:
                        old = db.execute('SELECT "Username", "Salt", "PasswordHash" FROM bili_user WHERE "Id"=1').fetchone()
                    except sqlite3.OperationalError:
                        old = None
                else:
                    old = None
                if old:
                    db.execute("INSERT INTO py_admin VALUES(1,?,?,?)", tuple(old))
                else:
                    salt, digest = hash_password(os.getenv("BILI_ADMIN_PASSWORD", "BiliTool@2233"))
                    db.execute("INSERT INTO py_admin VALUES(1,?,?,?)", ("admin", salt, digest))

    @staticmethod
    def _has_table(db, name):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    @staticmethod
    def cookie_uid(cookie):
        parts = dict(item.strip().split("=", 1) for item in cookie.split(";") if "=" in item)
        value = parts.get("DedeUserID", "")
        return value if value.isdigit() else ""

    def admin(self):
        with self.connect() as db:
            return dict(db.execute("SELECT * FROM py_admin WHERE id=1").fetchone())

    def login(self, username, password):
        admin = self.admin()
        return hmac.compare_digest(username, admin["username"]) and verify_password(password, admin["salt"], admin["password_hash"])

    def change_admin(self, username=None, old_password=None, new_password=None):
        admin = self.admin()
        if not verify_password(old_password or "", admin["salt"], admin["password_hash"]):
            raise ValueError("当前密码错误")
        if username is not None:
            username = username.strip()
            if not 1 <= len(username) <= 50:
                raise ValueError("管理员名称需为 1–50 个字符")
        if new_password is not None and len(new_password) < 8:
            raise ValueError("新密码至少 8 个字符")
        with self.connect() as db:
            if username is not None:
                db.execute("UPDATE py_admin SET username=? WHERE id=1", (username,))
            if new_password is not None:
                salt, digest = hash_password(new_password)
                db.execute("UPDATE py_admin SET salt=?,password_hash=? WHERE id=1", (salt, digest))

    def settings(self):
        with self.connect() as db:
            return {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM py_settings")}

    def set_settings(self, values):
        with self.connect() as db:
            db.executemany("INSERT INTO py_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           [(key, str(value)) for key, value in values.items()])

    def accounts(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM py_accounts ORDER BY position,id")]

    def save_account(self, cookie, account_id=None):
        uid = self.cookie_uid(cookie)
        if not uid or "SESSDATA=" not in cookie or "bili_jct=" not in cookie:
            raise ValueError("Cookie 需包含 DedeUserID、SESSDATA 和 bili_jct")
        with self.connect() as db:
            if account_id:
                db.execute("UPDATE py_accounts SET uid=?,cookie=? WHERE id=?", (uid, cookie, account_id))
            else:
                position = db.execute("SELECT count(*) FROM py_accounts").fetchone()[0]
                db.execute("INSERT INTO py_accounts(position,uid,cookie,created_at) VALUES(?,?,?,?)",
                           (position, uid, cookie, datetime.now().isoformat()))

    def delete_account(self, account_id):
        with self.connect() as db:
            db.execute("DELETE FROM py_accounts WHERE id=?", (account_id,))
            for position, row in enumerate(db.execute("SELECT id FROM py_accounts ORDER BY position,id")):
                db.execute("UPDATE py_accounts SET position=? WHERE id=?", (position, row[0]))

    def reorder_account(self, account_id, direction):
        rows = self.accounts()
        index = next((i for i, row in enumerate(rows) if row["id"] == account_id), None)
        if index is None or not 0 <= index + direction < len(rows):
            return
        rows[index], rows[index + direction] = rows[index + direction], rows[index]
        with self.connect() as db:
            for position, row in enumerate(rows):
                db.execute("UPDATE py_accounts SET position=? WHERE id=?", (position, row["id"]))

    def schedules(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM py_schedules ORDER BY task")]

    def set_schedule(self, task, cron, enabled):
        with self.connect() as db:
            db.execute("UPDATE py_schedules SET cron=?,enabled=? WHERE task=?", (cron, int(enabled), task))

    def claim_schedule(self, task, minute):
        with self.connect() as db:
            result = db.execute("UPDATE py_schedules SET last_fired=? WHERE task=? AND enabled=1 AND (last_fired IS NULL OR last_fired<>?)",
                                (minute, task, minute))
            return result.rowcount == 1

    def begin_run(self, task, trigger, uid=None):
        with self.connect() as db:
            result = db.execute("INSERT INTO py_runs(task,trigger,status,started_at,target_uid) VALUES(?,?,?,?,?)",
                                (task, trigger, "Running", datetime.now().isoformat(), uid))
            return result.lastrowid

    def finish_run(self, run_id, code, output):
        with self.connect() as db:
            db.execute("UPDATE py_runs SET status=?,finished_at=?,exit_code=?,output=? WHERE id=?",
                       ("Success" if code == 0 else "Failed", datetime.now().isoformat(), code, output[-100000:], run_id))

    def runs(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM py_runs ORDER BY id DESC LIMIT ?", (limit,))]

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM py_runs WHERE id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def record_account_run(self, run_id, uid, task, trigger, code):
        with self.connect() as db:
            db.execute("INSERT INTO py_task_records(run_id,uid,task,record_date,trigger,status) VALUES(?,?,?,?,?,?)",
                       (run_id, uid, task, datetime.now().date().isoformat(), trigger,
                        "Success" if code == 0 else "Failed"))

    def today_records(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM py_task_records WHERE record_date=? ORDER BY id DESC",
                              (datetime.now().date().isoformat(),)).fetchall()
            return [dict(row) for row in rows]

    def auto_attempts(self, uid, task):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM py_task_records WHERE uid=? AND task=? AND record_date=? AND trigger='Auto'",
                              (uid, task, datetime.now().date().isoformat())).fetchone()[0]

    def prune_records(self, days):
        from datetime import timedelta
        cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
        with self.connect() as db:
            db.execute("DELETE FROM py_task_records WHERE record_date<?", (cutoff,))
            db.execute("DELETE FROM py_cookie_notifications WHERE sent_date<?", (cutoff,))

    def mark_cookie_notified(self, uid):
        with self.connect() as db:
            result = db.execute("INSERT OR IGNORE INTO py_cookie_notifications(uid,sent_date) VALUES(?,?)",
                                (uid, datetime.now().date().isoformat()))
            return result.rowcount == 1
