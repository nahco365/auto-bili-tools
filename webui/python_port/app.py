"""Flask Web host for the Python BiliBiliToolPro port."""

import json
import base64
import hashlib
from io import BytesIO
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, build_opener

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bili_qinglong import Client, TASKS
from bili_login import open_json
from python_port.scheduler import Scheduler, validate_cron
from python_port.store import DEFAULT_SCHEDULES, Store


TASK_LABELS = {
    "Daily": "每日任务", "Manga": "漫画签到与阅读", "MangaPrivilege": "漫画权益",
    "Silver2Coin": "银瓜子兑换", "Charge": "B 币券充电", "VipPrivilege": "年度大会员权益",
    "VipBigPoint": "大会员积分", "LiveLottery": "天选抽奖",
    "LiveFansMedal": "粉丝勋章", "UnfollowBatched": "批量取关", "LiveSign": "直播签到",
    "Test": "测试 Cookie", "CookieTest": "测试 Cookie",
}

CONFIG_FIELDS = {
    "DailyTaskConfig": [("IsEnable", "启用", "bool", "true"), ("IsWatchVideo", "观看视频", "bool", "true"),
        ("IsShareVideo", "分享视频", "bool", "true"), ("IsDonateCoinForArticle", "优先专栏投币", "bool", "false"),
        ("NumberOfCoins", "每日目标投币数", "number", "5"), ("NumberOfProtectedCoins", "保留硬币数", "number", "0"),
        ("SaveCoinsWhenLv6", "六级后停止投币", "bool", "false"), ("CoinDonationStopLevel", "停止投币等级", "number", "0"),
        ("SelectLike", "投币时点赞", "bool", "true"), ("SupportUpIds", "优先 UP UID 列表", "text", ""),
        ("DevicePlatform", "设备平台", "text", "android")],
    "MangaTaskConfig": [("IsEnable", "启用", "bool", "true"), ("CustomComicId", "漫画 ID", "number", "27355"),
        ("CustomEpId", "章节 ID", "number", "381662")],
    "MangaPrivilegeTaskConfig": [("IsEnable", "启用", "bool", "true")],
    "Silver2CoinTaskConfig": [("IsEnable", "启用", "bool", "true")],
    "ChargeTaskConfig": [("IsEnable", "启用", "bool", "true"), ("AutoChargeUpId", "单账号目标 UP UID", "text", ""),
        ("ChargeComment", "充电留言", "text", "")],
    "VipPrivilegeConfig": [("IsEnable", "启用", "bool", "true")],
    "VipBigPointConfig": [("IsEnable", "启用", "bool", "true"), ("ViewBangumis", "番剧 SSID", "text", "33378")],
    "LiveLotteryTaskConfig": [("IsEnable", "启用", "bool", "true"), ("ExcludeAwardNames", "排除奖品关键词，用 | 分隔", "text", ""),
        ("IncludeAwardNames", "包含奖品关键词，用 | 分隔", "text", ""), ("AutoGroupFollowings", "自动分组新增关注", "bool", "true"),
        ("DenyUids", "主播 UID 黑名单", "text", "")],
    "LiveFansMedalTaskConfig": [("IsEnable", "启用", "bool", "true"), ("FollowDailyTaskLimit", "按每日任务上限执行", "bool", "false"),
        ("EnableLike", "点赞", "bool", "true"), ("EnableDanmaku", "发送弹幕", "bool", "true"),
        ("EnableWatch", "观看", "bool", "true"), ("DanmakuOnlyWhenOffline", "仅未开播时发送弹幕", "bool", "false"),
        ("OnlySelectedAnchors", "仅选中主播", "bool", "false"), ("IncludedAnchorIds", "包含主播 UID", "text", ""),
        ("ExcludedAnchorIds", "排除主播 UID", "text", ""), ("DanmakuContent", "弹幕内容", "text", "OvO"),
        ("LikeNumber", "点赞次数", "number", "30"), ("SendDanmakuNumber", "弹幕次数", "number", "1"),
        ("HeartBeatNumber", "观看分钟数", "number", "70"),
        ("HeartBeatSendGiveUpThreshold", "心跳失败放弃次数", "number", "5"),
        ("SendDanmakugiveUpThreshold", "弹幕失败放弃次数", "number", "3")],
    "UnfollowBatchedTaskConfig": [("IsEnable", "启用", "bool", "true"), ("GroupName", "分组名称", "text", "天选时刻"),
        ("Count", "每次取关数量", "number", "20"), ("RetainUids", "保留 UID", "text", "")],
    "Security": [("IsSkipDailyTask", "暂停每日任务", "bool", "false"),
        ("RandomSleepMaxMin", "随机延迟最大分钟数", "number", "10"),
        ("IntervalSecondsBetweenRequestApi", "API 请求间隔秒数", "number", "3"),
        ("IntervalMethodTypes", "请求间隔适用方法", "text", "GET,POST"),
        ("UserAgent", "浏览器 User-Agent", "text", ""),
        ("UserAgentApp", "App User-Agent", "text", ""),
        ("WebProxy", "HTTP 代理", "text", "")],
    "DeviceCookie": [("Buvid3", "固定 buvid3", "text", ""), ("Buvid4", "固定 buvid4", "text", ""),
        ("BNut", "固定 b_nut", "text", "")],
    "AutoRecoverConfig": [("IsEnable", "自动补做", "bool", "true"),
        ("IntervalHours", "检查间隔小时数", "number", "2"),
        ("RecordRetentionDays", "记录保留天数", "number", "3")],
}

NOTIFICATION_FIELDS = [
    ("FailureEnabled", "任务失败通知", "bool", "false"),
    ("CookieExpiryEnabled", "Cookie 过期通知", "bool", "false"),
    ("WebhookUrl", "自定义 Webhook URL", "text", ""),
    ("TelegramBotToken", "Telegram Bot Token", "text", ""),
    ("TelegramChatId", "Telegram Chat ID", "text", ""),
    ("ServerChanKey", "Server 酱 Key", "text", ""),
    ("PushPlusToken", "PushPlus Token", "text", ""),
    ("GotifyUrl", "Gotify URL", "text", ""),
    ("GotifyToken", "Gotify Token", "text", ""),
    ("WorkWeixinWebhook", "企业微信群机器人 Webhook", "text", ""),
    ("DingTalkWebhook", "钉钉群机器人 Webhook", "text", ""),
    ("TeamsWebhook", "Microsoft Teams Webhook", "text", ""),
    ("CustomApiUrl", "自定义 API 地址", "text", ""),
    ("CustomApiBody", "自定义 JSON 模板（含 #msg#）", "text", '{"message":#msg#}'),
    ("WorkWeixinCorpId", "企业微信应用 CorpId", "text", ""),
    ("WorkWeixinAgentId", "企业微信应用 AgentId", "text", ""),
    ("WorkWeixinSecret", "企业微信应用 Secret", "text", ""),
    ("WorkWeixinToUser", "企业微信应用接收人", "text", "@all"),
]


def _secret_file(path):
    target = Path(path).with_suffix(".secret")
    if not target.exists():
        target.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    return target.read_text(encoding="utf-8").strip()


def create_app(db_path=None, start_scheduler=False):
    db_path = db_path or os.getenv("BILI_PY_DB", str(ROOT / "data" / "bilitool.sqlite"))
    store = Store(db_path)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.getenv("BILI_PY_SECRET") or _secret_file(db_path)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.getenv("BILI_HTTPS", "false").lower() == "true")
    app.extensions["bili_store"] = store
    qr_sessions = {}
    medal_cache = {}

    def notify(task, output):
        from python_port.notify import send_failure
        send_failure(store.settings(), task, output)

    scheduler = Scheduler(store, notify=notify)
    app.extensions["bili_scheduler"] = scheduler
    if start_scheduler:
        scheduler.start()

    @app.context_processor
    def inject_globals():
        return {"task_labels": TASK_LABELS, "csrf_token": session.get("csrf", ""),
                "admin_name": session.get("username", "")}

    @app.before_request
    def protect():
        session.setdefault("csrf", secrets.token_urlsafe(24))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not token or not secrets.compare_digest(token, session["csrf"]):
                abort(400, "CSRF 校验失败")
        if request.endpoint not in ("login", "static", "health") and not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("authenticated"):
            return redirect(url_for("home"))
        if request.method == "POST":
            if store.login(request.form.get("username", ""), request.form.get("password", "")):
                token = session["csrf"]
                session.clear()
                session.update(authenticated=True, username=request.form["username"], csrf=token)
                target = request.args.get("next", "")
                return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("home"))
            flash("用户名或密码错误", "error")
        return render_template("login.html", title="登录")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def home():
        runs = store.runs(10)
        return render_template("home.html", title="首页", accounts=store.accounts(), runs=runs,
                               schedules=store.schedules())

    @app.get("/accounts")
    def accounts():
        return render_template("accounts.html", title="B 站账号", accounts=store.accounts())

    @app.post("/accounts")
    def add_account():
        try:
            store.save_account(request.form.get("cookie", "").strip())
            flash("账号已添加", "success")
        except (ValueError, sqlite3.IntegrityError) as exc:
            flash(f"添加失败：{exc}", "error")
        return redirect(url_for("accounts"))

    @app.post("/accounts/<int:account_id>/update")
    def update_account(account_id):
        try:
            store.save_account(request.form.get("cookie", "").strip(), account_id)
            flash("Cookie 已更新", "success")
        except (ValueError, sqlite3.IntegrityError) as exc:
            flash(f"更新失败：{exc}", "error")
        return redirect(url_for("accounts"))

    @app.post("/accounts/<int:account_id>/delete")
    def delete_account(account_id):
        store.delete_account(account_id)
        flash("账号已删除", "success")
        return redirect(url_for("accounts"))

    @app.post("/accounts/<int:account_id>/move/<direction>")
    def move_account(account_id, direction):
        store.reorder_account(account_id, -1 if direction == "up" else 1)
        return redirect(url_for("accounts"))

    @app.post("/accounts/<int:account_id>/check")
    def check_account(account_id):
        item = next((x for x in store.accounts() if x["id"] == account_id), None)
        if not item:
            abort(404)
        try:
            data = Client(item["cookie"]).get("/x/web-interface/nav")
            if not data.get("isLogin"):
                raise ValueError("登录已失效")
            flash(f"UID {item['uid']}：{data.get('uname')}，Cookie 有效", "success")
        except Exception as exc:
            flash(f"UID {item['uid']}：检查失败：{exc}", "error")
        return redirect(url_for("accounts"))

    @app.post("/accounts/qr/start")
    def qr_start():
        import qrcode
        from qrcode.image.svg import SvgImage
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        result = open_json(opener, "https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
        if result.get("code") != 0:
            return jsonify(error=result.get("message", "生成二维码失败")), 502
        token = secrets.token_urlsafe(24)
        qr_sessions[token] = {"jar": jar, "opener": opener, "key": result["data"]["qrcode_key"], "created": time.time()}
        image = qrcode.make(result["data"]["url"], image_factory=SvgImage)
        buffer = BytesIO()
        image.save(buffer)
        data_url = "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode()
        return jsonify(token=token, image=data_url)

    @app.post("/accounts/qr/poll")
    def qr_poll():
        token = (request.json or {}).get("token", "")
        item = qr_sessions.get(token)
        if not item or time.time() - item["created"] > 180:
            return jsonify(status="expired")
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?" + urlencode({
            "qrcode_key": item["key"], "source": "main_mini"})
        result = open_json(item["opener"], url)
        code = (result.get("data") or {}).get("code")
        if code != 0:
            return jsonify(status="expired" if code == 86038 else "waiting", message=(result.get("data") or {}).get("message"))
        fields = {cookie.name: cookie.value for cookie in item["jar"] if cookie.name in
                  ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4", "b_nut", "_uuid")}
        if not {"SESSDATA", "bili_jct", "DedeUserID"} <= fields.keys():
            return jsonify(status="error", message="扫码成功，但未收到完整 Cookie"), 502
        cookie = "; ".join(f"{key}={value}" for key, value in fields.items())
        try:
            old = next((x for x in store.accounts() if x["uid"] == fields.get("DedeUserID")), None)
            store.save_account(cookie, old["id"] if old else None)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return jsonify(status="error", message=str(exc)), 400
        qr_sessions.pop(token, None)
        return jsonify(status="success")

    @app.get("/today")
    def today():
        from python_port.today import build_today
        return render_template("today.html", title="今日任务", snapshots=build_today(store, probe=request.args.get("probe") == "1"),
                               probed=request.args.get("probe") == "1")

    @app.get("/medals")
    def medals_page():
        accounts = store.accounts()
        uid = request.args.get("uid") or (accounts[0]["uid"] if accounts else "")
        account = next((item for item in accounts if item["uid"] == uid), None)
        cards, error = [], None
        if account:
            fingerprint = hashlib.sha256(account["cookie"].encode()).hexdigest()
            key = (uid, fingerprint, datetime.now().date().isoformat())
            cached = medal_cache.get(key)
            if request.args.get("refresh") == "1" or not cached or time.time() - cached[0] > 60:
                try:
                    from python_port.medal_dashboard import read_medals
                    cards = read_medals(account["cookie"])
                    medal_cache.clear()
                    medal_cache[key] = (time.time(), cards)
                except Exception as exc:
                    error = f"粉丝勋章加载失败：{exc}"
            else:
                cards = cached[1]
        return render_template("medals.html", title="粉丝勋章", accounts=accounts,
                               selected_uid=uid, cards=cards, error=error)

    @app.get("/schedules")
    def schedules():
        return render_template("schedules.html", title="计划任务", schedules=store.schedules(), runs=store.runs(30))

    @app.post("/schedules/<task>/save")
    def schedule_save(task):
        if task not in DEFAULT_SCHEDULES:
            abort(404)
        cron = request.form.get("cron", "").strip()
        try:
            validate_cron(cron)
            store.set_schedule(task, cron, "enabled" in request.form)
            flash("计划已保存", "success")
        except ValueError as exc:
            flash(f"Cron 格式错误：{exc}", "error")
        return redirect(url_for("schedules"))

    @app.post("/tasks/<task>/run")
    def run_task(task):
        if task not in TASKS:
            abort(404)
        uid = request.form.get("uid") or None
        if uid and not any(item["uid"] == uid for item in store.accounts()):
            abort(404)
        run_id = scheduler.submit(task, uid=uid)
        flash("任务已启动" if run_id else "任务正在执行中", "success" if run_id else "error")
        return redirect(url_for("run_detail", run_id=run_id) if run_id else url_for("schedules"))

    @app.get("/runs/<int:run_id>")
    def run_detail(run_id):
        item = store.run(run_id)
        if not item:
            abort(404)
        return render_template("run.html", title="执行记录", run=item)

    @app.get("/api/runs/<int:run_id>")
    def run_json(run_id):
        item = store.run(run_id)
        if not item:
            abort(404)
        return jsonify(item)

    @app.route("/settings/<section>", methods=["GET", "POST"])
    def settings(section):
        fields = CONFIG_FIELDS.get(section)
        if fields is None:
            abort(404)
        if request.method == "POST":
            values = {}
            previous = store.settings()
            for name, _, kind, default in fields:
                value = ("true" if name in request.form else "false") if kind == "bool" else request.form.get(name, previous.get(f"{section}:{name}", default)).strip()
                if kind == "number":
                    try:
                        int(value)
                    except ValueError:
                        flash(f"{name} 必须是整数", "error")
                        return redirect(url_for("settings", section=section))
                values[f"{section}:{name}"] = value
            if section == "ChargeTaskConfig":
                for account in store.accounts():
                    target = request.form.get("target_" + account["uid"], "").strip()
                    if target and (not target.isdigit() or int(target) <= 0):
                        flash(f"账号 UID {account['uid']} 的充电目标必须是正整数 UID", "error")
                        return redirect(url_for("settings", section=section))
                    values[f"ChargeTaskConfig:AutoChargeUpId:{account['uid']}"] = target
            store.set_settings(values)
            flash("配置已保存", "success")
            return redirect(url_for("settings", section=section))
        current = store.settings()
        return render_template("settings.html", title=section, section=section,
                               fields=fields, current=current, accounts=store.accounts())

    @app.route("/notifications", methods=["GET", "POST"])
    def notifications():
        if request.method == "POST":
            values = {"Notification:" + name: ("true" if name in request.form else "false") if kind == "bool"
                      else request.form.get(name, "").strip() for name, _, kind, _ in NOTIFICATION_FIELDS}
            store.set_settings(values)
            flash("通知配置已保存", "success")
            return redirect(url_for("notifications"))
        return render_template("settings.html", title="通知", section="Notification",
                               fields=NOTIFICATION_FIELDS, current=store.settings())

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "username":
                    store.change_admin(username=request.form.get("username", ""),
                                       old_password=request.form.get("current_password", ""))
                elif action == "password":
                    store.change_admin(old_password=request.form.get("current_password", ""),
                                       new_password=request.form.get("new_password", ""))
                else:
                    abort(400)
                session.clear()
                flash("凭据已更新，请重新登录", "success")
                return redirect(url_for("login"))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("admin.html", title="管理员", admin=store.admin())

    @app.get("/about")
    def about():
        return render_template("about.html", title="关于")

    return app


if __name__ == "__main__":
    app = create_app(start_scheduler=True)
    app.run(host=os.getenv("BILI_PY_HOST", "127.0.0.1"), port=int(os.getenv("BILI_PY_PORT", "8080")), threaded=True)
