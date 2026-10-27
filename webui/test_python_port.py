import sqlite3
import os
import subprocess
import tempfile
import unittest
import base64
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from python_port.app import create_app
from python_port.scheduler import cron_matches, last_fire_today
from python_port.store import Store, hash_password, verify_password


class StoreTests(unittest.TestCase):
    def test_imports_only_unprefixed_cookie_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "BiliBiliCookies__1": "DedeUserID=42; SESSDATA=new; bili_jct=x",
                "Ray_BiliBiliCookies__2": "DedeUserID=43; SESSDATA=old; bili_jct=x",
        }, clear=True):
            store = Store(Path(folder) / "web.sqlite")
            self.assertEqual([account["uid"] for account in store.accounts()], ["42"])

    def test_scf_handler_uses_python_task_entry(self):
        from python_port.platforms.scf import main_handler
        with patch("python_port.platforms.scf.main", return_value=0) as entry:
            result = main_handler({"task": "Daily&Manga"}, None)
        self.assertEqual(result, {"tasks": ["Daily", "Manga"], "exit_code": 0})
        entry.assert_called_once_with(["Daily", "Manga"])
        with self.assertRaises(ValueError):
            main_handler({"task": "Unknown"}, None)

    def test_kubectl_output_does_not_apply(self):
        from python_port.platforms.kubectl_bilipro import main
        with patch("python_port.platforms.kubectl_bilipro.subprocess.run") as command:
            with patch("builtins.print") as output:
                self.assertEqual(main(["init", "--image", "example/bili:1", "--output"]), 0)
        command.assert_not_called()
        self.assertIn("example/bili:1", output.call_args.args[0])

    def test_password_uses_original_pbkdf2_format(self):
        salt, digest = hash_password("example-pass")
        self.assertTrue(verify_password("example-pass", salt, digest))
        self.assertFalse(verify_password("wrong-pass", salt, digest))

    def test_imports_legacy_settings_accounts_and_admin(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "old.sqlite"
            salt, digest = hash_password("legacy-pass")
            connection = sqlite3.connect(db_path)
            connection.execute('CREATE TABLE bili_appsettings ("Key" TEXT PRIMARY KEY,"Value" TEXT NOT NULL)')
            connection.execute('INSERT INTO bili_appsettings VALUES (?,?)',
                               ("BiliBiliCookies:0", "DedeUserID=42; SESSDATA=x; bili_jct=y"))
            connection.execute('CREATE TABLE bili_user ("Id" INTEGER,"Username" TEXT,"Salt" TEXT,"PasswordHash" TEXT)')
            connection.execute('INSERT INTO bili_user VALUES (1,?,?,?)', ("legacy", salt, digest))
            connection.commit()
            connection.close()
            store = Store(db_path)
            self.assertEqual(store.accounts()[0]["uid"], "42")
            self.assertTrue(store.login("legacy", "legacy-pass"))

    def test_cron_quartz_and_crontab(self):
        self.assertTrue(cron_matches("0 0 15 * * ?", datetime(2026, 10, 27, 15, 0, 0)))
        self.assertFalse(cron_matches("0 0 15 * * ?", datetime(2026, 10, 27, 15, 1, 0)))
        self.assertTrue(cron_matches("0 9 * * *", datetime(2026, 10, 27, 9, 0, 0)))
        self.assertTrue(cron_matches("0 0 0 L * ?", datetime(2026, 10, 31, 0, 0, 0)))
        self.assertTrue(cron_matches("0 0 9 ? * TUE", datetime(2026, 10, 27, 9, 0, 0)))
        self.assertEqual(last_fire_today("0 9,18 * * *", "2026-10-27", "2026-10-27T10:00:00"),
                         datetime(2026, 10, 27, 9, 0, 0))


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.app = create_app(str(Path(self.folder.name) / "web.sqlite"))
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.store = self.app.extensions["bili_store"]
        with self.client.session_transaction() as session:
            session["csrf"] = "test-token"

    def tearDown(self):
        self.folder.cleanup()

    def login(self):
        response = self.client.post("/login", data={"username": "admin", "password": "BiliTool@2233",
                                                    "csrf_token": "test-token"})
        self.assertEqual(response.status_code, 302)

    def test_requires_login_and_csrf(self):
        self.assertEqual(self.client.get("/accounts").status_code, 302)
        self.assertEqual(self.client.post("/login", data={"username": "admin", "password": "BiliTool@2233"}).status_code, 400)
        self.login()
        accounts_page = self.client.get("/accounts")
        self.assertEqual(accounts_page.status_code, 200)
        self.assertIn(b"Ray_QingLongConfig__ClientId", accounts_page.data)
        self.assertIn(b"Ray_QingLongConfig__ClientSecret", accounts_page.data)
        self.assertEqual(self.client.post("/accounts", data={"cookie": "invalid"}).status_code, 400)

    def test_account_settings_and_admin_flow(self):
        self.login()
        cookie = "DedeUserID=42; SESSDATA=x; bili_jct=y"
        self.client.post("/accounts", data={"csrf_token": "test-token", "cookie": cookie})
        self.assertEqual(self.store.accounts()[0]["uid"], "42")
        self.client.post("/settings/DailyTaskConfig", data={"csrf_token": "test-token",
                         "IsEnable": "on", "NumberOfCoins": "2", "NumberOfProtectedCoins": "1"})
        self.assertEqual(self.store.settings()["DailyTaskConfig:NumberOfCoins"], "2")
        self.client.post("/admin", data={"csrf_token": "test-token", "action": "username",
                         "username": "new-admin", "current_password": "BiliTool@2233"})
        self.assertTrue(self.store.login("new-admin", "BiliTool@2233"))
        self.assertEqual(self.client.get("/accounts").status_code, 302)

    def test_charge_settings_store_each_accounts_target(self):
        self.login()
        self.store.save_account("DedeUserID=42; SESSDATA=x; bili_jct=y")
        self.store.save_account("DedeUserID=43; SESSDATA=x; bili_jct=y")
        response = self.client.post("/settings/ChargeTaskConfig", data={
            "csrf_token": "test-token", "IsEnable": "on", "AutoChargeUpId": "",
            "ChargeComment": "", "target_42": "123", "target_43": "456"})
        self.assertEqual(response.status_code, 302)
        settings = self.store.settings()
        self.assertEqual(settings["ChargeTaskConfig:AutoChargeUpId:42"], "123")
        self.assertEqual(settings["ChargeTaskConfig:AutoChargeUpId:43"], "456")
        self.assertIn(b"target_42", self.client.get("/settings/ChargeTaskConfig").data)

    def test_schedule_save_and_log_page(self):
        self.login()
        self.client.post("/schedules/Daily/save", data={"csrf_token": "test-token", "cron": "0 12 * * *", "enabled": "on"})
        self.assertEqual(next(x for x in self.store.schedules() if x["task"] == "Daily")["cron"], "0 12 * * *")
        self.assertEqual(self.client.get("/schedules").status_code, 200)
        run_id = self.store.begin_run("Daily", "Manual")
        self.store.finish_run(run_id, 0, "completed")
        self.assertIn(b"completed", self.client.get(f"/runs/{run_id}").data)

    def test_today_redo_targets_only_selected_uid(self):
        self.login()
        self.store.save_account("DedeUserID=42; SESSDATA=x; bili_jct=y")
        self.assertEqual(self.client.get("/today").status_code, 200)
        scheduler = self.app.extensions["bili_scheduler"]
        with patch.object(scheduler, "submit", return_value=12) as submit:
            response = self.client.post("/tasks/Daily/run", data={"csrf_token": "test-token", "uid": "42"})
        self.assertEqual(response.status_code, 302)
        submit.assert_called_once_with("Daily", uid="42")

    def test_medal_dashboard_caches_one_account(self):
        self.login()
        self.store.save_account("DedeUserID=42; SESSDATA=x; bili_jct=y")
        card = {"anchor": "7", "name": "主播", "medal": "牌子", "level": 1,
                "live": True, "tasks": [], "error": None}
        with patch("python_port.medal_dashboard.read_medals", return_value=[card]) as read:
            self.assertEqual(self.client.get("/medals?uid=42").status_code, 200)
            self.assertIn("牌子".encode(), self.client.get("/medals?uid=42").data)
            read.assert_called_once()

    def test_scheduler_runs_accounts_independently(self):
        from python_port.scheduler import Scheduler
        self.store.save_account("DedeUserID=42; SESSDATA=first; bili_jct=y")
        self.store.save_account("DedeUserID=43; SESSDATA=second; bili_jct=y")
        scheduler = Scheduler(self.store)
        run_id = self.store.begin_run("Manga", "Manual")
        environments = []
        def fake_run(*args, **kwargs):
            environments.append(kwargs["env"].copy())
            return SimpleNamespace(stdout="ok", stderr="", returncode=0)
        with patch("python_port.scheduler.subprocess.run", side_effect=fake_run), \
             patch.dict(os.environ, {"Ray_BiliBiliCookies__9": "stale"}):
            scheduler._execute("Manga", "Manual", run_id, None)
        self.assertEqual(len(environments), 2)
        self.assertIn("SESSDATA=first", environments[0]["BiliBiliCookies__0"])
        self.assertIn("SESSDATA=second", environments[1]["BiliBiliCookies__0"])
        self.assertNotIn("Ray_BiliBiliCookies__9", environments[0])
        self.assertEqual(environments[0]["BILI_ACCOUNT_COUNT"], "2")
        self.assertEqual(len(self.store.today_records()), 2)

    def test_scheduler_records_timeout_and_continues_to_next_account(self):
        from python_port.scheduler import Scheduler
        self.store.save_account("DedeUserID=42; SESSDATA=first; bili_jct=y")
        self.store.save_account("DedeUserID=43; SESSDATA=second; bili_jct=y")
        scheduler = Scheduler(self.store)
        run_id = self.store.begin_run("Manga", "Manual")
        with patch("python_port.scheduler.subprocess.run", side_effect=[
            subprocess.TimeoutExpired("task", 21600, output=b"partial"),
            SimpleNamespace(stdout="ok", stderr="", returncode=0),
        ]) as run:
            scheduler._execute("Manga", "Manual", run_id, None)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.store.run(run_id)["status"], "Failed")
        self.assertIn("partial", self.store.run(run_id)["output"])
        self.assertEqual({row["uid"] for row in self.store.today_records()}, {"42", "43"})

    def test_scheduler_persists_refreshed_device_cookie(self):
        from python_port.scheduler import Scheduler
        self.store.save_account("DedeUserID=42; SESSDATA=first; bili_jct=y")
        scheduler = Scheduler(self.store)
        run_id = self.store.begin_run("Test", "Manual")
        def fake_run(*args, **kwargs):
            Path(kwargs["env"]["BILI_COOKIE_OUTPUT"]).write_text(
                "DedeUserID=42; SESSDATA=first; bili_jct=y; buvid3=new", encoding="utf-8")
            return SimpleNamespace(stdout="ok", stderr="", returncode=0)
        with patch("python_port.scheduler.subprocess.run", side_effect=fake_run):
            scheduler._execute("Test", "Manual", run_id, None)
        self.assertIn("buvid3=new", self.store.accounts()[0]["cookie"])
        self.assertEqual(self.store.run(run_id)["status"], "Success")

    def test_qr_start_returns_local_svg_and_rejects_missing_cookies(self):
        self.login()
        response_data = {"code": 0, "data": {"url": "https://example.test/qr", "qrcode_key": "key"}}
        with patch("python_port.app.open_json", return_value=response_data):
            response = self.client.post("/accounts/qr/start", data={"csrf_token": "test-token"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(base64.b64decode(payload["image"].split(",", 1)[1]).startswith(b"<?xml"))
        with patch("python_port.app.open_json", return_value={"code": 0, "data": {"code": 0}}):
            response = self.client.post("/accounts/qr/poll", json={"token": payload["token"]},
                                        headers={"X-CSRF-Token": "test-token"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.store.accounts(), [])


if __name__ == "__main__":
    unittest.main()
