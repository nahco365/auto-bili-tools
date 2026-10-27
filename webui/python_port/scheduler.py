"""Persistent schedules and subprocess execution for the Python tasks."""

import calendar
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "bili_qinglong.py"


def _field_matches(field, value, minimum, maximum, last=None):
    if field in ("*", "?"):
        return True
    if field == "L" and last is not None:
        return value == last
    for part in field.split(","):
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ValueError("cron step must be positive")
        else:
            base, step = part, 1
        if base in ("*", "?"):
            start, end = minimum, maximum
        elif "-" in base:
            start, end = (int(x) for x in base.split("-", 1))
        else:
            start = int(base)
            end = maximum if "/" in part else start
        if not minimum <= start <= end <= maximum:
            raise ValueError("cron field out of range")
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def cron_matches(expression, when):
    fields = expression.split()
    if len(fields) == 5:
        minute, hour, day, month, weekday = fields
        second = "0"
    elif len(fields) in (6, 7):
        second, minute, hour, day, month, weekday = fields[:6]
        if len(fields) == 7 and not _field_matches(fields[6], when.year, 1970, 2099):
            return False
    else:
        raise ValueError("cron 必须是 5、6 或 7 段")
    month_names = {name: str(i) for i, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
    week_names = {name: str(i) for i, name in enumerate(
        ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"), 1 if len(fields) >= 6 else 0)}
    month = re.sub(r"[A-Za-z]{3}", lambda match: month_names.get(match.group().upper(), match.group()), month)
    weekday = re.sub(r"[A-Za-z]{3}", lambda match: week_names.get(match.group().upper(), match.group()), weekday)
    # Quartz uses 1=Sunday; traditional crontab uses 0=Sunday.
    quartz = len(fields) >= 6
    day_of_week = ((when.weekday() + 1) % 7) + (1 if quartz else 0)
    maximum_weekday = 7 if quartz else 6
    checks = (
        _field_matches(second, when.second, 0, 59),
        _field_matches(minute, when.minute, 0, 59),
        _field_matches(hour, when.hour, 0, 23),
        _field_matches(day, when.day, 1, 31, calendar.monthrange(when.year, when.month)[1]),
        _field_matches(month, when.month, 1, 12),
        _field_matches(weekday, day_of_week, 1 if quartz else 0, maximum_weekday),
    )
    return all(checks)


def validate_cron(expression):
    sample = datetime(2026, 1, 1)
    cron_matches(expression, sample)


@lru_cache(maxsize=128)
def last_fire_today(expression, date_text, before=None):
    day = datetime.fromisoformat(date_text)
    cutoff = datetime.fromisoformat(before) if before else None
    fields = expression.split()
    second_field = fields[0] if len(fields) >= 6 else "0"
    seconds = [int(second_field)] if second_field.isdigit() else range(60)
    latest = None
    for hour in range(24):
        for minute in range(60):
            for second in seconds:
                candidate = day.replace(hour=hour, minute=minute, second=second)
                if cutoff and candidate > cutoff:
                    return latest
                if cron_matches(expression, candidate):
                    latest = candidate
    return latest


class Scheduler:
    def __init__(self, store, notify=None):
        self.store = store
        self.notify = notify
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bili-task")
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.active = set()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="bili-scheduler", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, task, trigger="Manual", uid=None):
        key = (task, uid)
        with self.lock:
            if any(active_task == task and (active_uid is None or uid is None or active_uid == uid)
                   for active_task, active_uid in self.active):
                return None
            self.active.add(key)
        run_id = self.store.begin_run(task, trigger, uid)
        self.executor.submit(self._execute, task, trigger, run_id, uid)
        return run_id

    def _execute(self, task, trigger, run_id, uid):
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            for key, value in self.store.settings().items():
                if key.lower().startswith("bilibilicookies:"):
                    continue
                env["Ray_" + key.replace(":", "__")] = value
            for name in list(env):
                if name.lower().startswith(("bilibilicookies__", "ray_bilibilicookies__")):
                    env.pop(name)
            all_accounts = self.store.accounts()
            env["BILI_ACCOUNT_COUNT"] = str(len(all_accounts))
            accounts = [item for item in all_accounts if uid is None or item["uid"] == uid]
            if not accounts:
                raise ValueError("未配置 B 站账号")
            chunks, failures = [], 0
            for item in accounts:
                env["BiliBiliCookies__0"] = item["cookie"]
                descriptor, cookie_path = tempfile.mkstemp(prefix="bili-cookie-", dir=self.store.path.parent)
                os.close(descriptor)
                env["BILI_COOKIE_OUTPUT"] = cookie_path
                try:
                    try:
                        result = subprocess.run([sys.executable, str(SCRIPT), task], cwd=SCRIPT.parent,
                                                env=env, capture_output=True, text=True, timeout=21600,
                                                encoding="utf-8", errors="replace")
                        account_output = result.stdout + result.stderr
                        account_code = result.returncode
                    except subprocess.TimeoutExpired as exc:
                        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                        account_output = stdout + stderr + "\n任务超过 6 小时，已停止"
                        account_code = 124
                    updated_cookie = Path(cookie_path).read_text(encoding="utf-8")
                    if updated_cookie:
                        self.store.save_account(updated_cookie, item["id"])
                finally:
                    Path(cookie_path).unlink(missing_ok=True)
                chunks.append(f"===== UID {item['uid']} =====\n" + account_output)
                self.store.record_account_run(run_id, item["uid"], task, trigger, account_code)
                if account_code and any(marker in account_output for marker in
                                             ("Cookie 已失效", "登录失败", "Cookie 需要")):
                    if self.store.mark_cookie_notified(item["uid"]):
                        from python_port.notify import send_cookie_expiry
                        send_cookie_expiry(self.store.settings(), item["uid"])
                failures += account_code != 0
            output = "\n".join(chunks)
            code = 1 if failures else 0
        except Exception as exc:
            output = f"任务启动失败：{type(exc).__name__}: {exc}"
            code = 1
        finally:
            with self.lock:
                self.active.discard((task, uid))
        self.store.finish_run(run_id, code, output)
        if code and self.notify:
            try:
                self.notify(task, output[-3000:])
            except Exception:
                pass

    def _loop(self):
        while not self.stop_event.is_set():
            now = datetime.now().replace(microsecond=0)
            key = now.isoformat()
            for schedule in self.store.schedules():
                if not schedule["enabled"]:
                    continue
                try:
                    due = cron_matches(schedule["cron"], now)
                except ValueError:
                    continue
                if due and self.store.claim_schedule(schedule["task"], key):
                    self.submit(schedule["task"], "Scheduled")
            settings = self.store.settings()
            interval = max(1, min(24, int(settings.get("AutoRecoverConfig:IntervalHours", "2"))))
            if now.hour % interval == 0 and now.minute == 0 and now.second == 0:
                self._auto_recover(now)
                self.store.prune_records(max(1, min(90, int(settings.get("AutoRecoverConfig:RecordRetentionDays", "3")))))
            self.stop_event.wait(max(.1, 1 - time.time() % 1))

    def _auto_recover(self, now):
        settings = self.store.settings()
        if settings.get("AutoRecoverConfig:IsEnable", "true").lower() != "true":
            return
        records = self.store.today_records()
        latest = {}
        for row in records:
            latest.setdefault((row["uid"], row["task"]), row)
        for schedule in self.store.schedules():
            if not schedule["enabled"]:
                continue
            try:
                due = last_fire_today(schedule["cron"], now.date().isoformat(), now.isoformat())
            except ValueError:
                continue
            if due is None or now < due + timedelta(minutes=10):
                continue
            for account in self.store.accounts():
                row = latest.get((account["uid"], schedule["task"]))
                if row and row["status"] == "Success":
                    continue
                if self.store.auto_attempts(account["uid"], schedule["task"]) >= 3:
                    continue
                self.submit(schedule["task"], "Auto", account["uid"])
