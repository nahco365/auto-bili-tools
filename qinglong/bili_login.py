"""QR sign-in and Qinglong environment persistence."""

import json
import logging
import os
import time
from http.cookiejar import CookieJar
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from bili_qinglong import ApiError, setting


LOG = logging.getLogger("bili")


def terminal_qr(value, border=4):
    """Render a scannable QR using block characters on a dark terminal."""
    from qrcodegen import QrCode

    qr = QrCode.encode_text(value, QrCode.Ecc.MEDIUM)
    side = qr.get_size()
    invert = setting("LoginConfig__QrLightBackground").lower() in ("1", "true", "yes", "on")

    def filled(x, y):
        dark = qr.get_module(x, y)
        return dark if invert else not dark

    lines = []
    for y in range(-border, side + border, 2):
        line = []
        for x in range(-border, side + border):
            upper, lower = filled(x, y), filled(x, y + 1)
            line.append("█" if upper and lower else "▀" if upper else "▄" if lower else " ")
        lines.append("".join(line))
    return "\n".join(lines)


def open_json(opener, url, method="GET", data=None, token=""):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = token
    with opener.open(Request(url, data=body, method=method, headers=headers), timeout=20) as response:
        return json.load(response)


def save_qinglong(cookie):
    client_id = setting("QingLongConfig__ClientId")
    secret = setting("QingLongConfig__ClientSecret")
    if not client_id or not secret:
        LOG.warning("未配置青龙 OpenAPI；请手动将 Cookie 添加为 BiliBiliCookies__N")
        return False
    base = setting("QingLongConfig__Url", "http://127.0.0.1:5700").rstrip("/")
    opener = build_opener()
    auth = open_json(opener, base + "/open/auth/token?" + urlencode({"client_id": client_id, "client_secret": secret}))
    if auth.get("code") != 200:
        raise ApiError("青龙 OpenAPI 鉴权失败")
    item = auth["data"]
    token = item["token_type"] + " " + item["token"]
    envs = open_json(opener, base + "/open/envs?" + urlencode({"searchValue": "BiliBiliCookies__"}), token=token)
    if envs.get("code") != 200:
        raise ApiError("青龙环境变量查询失败")
    uid = dict(part.strip().split("=", 1) for part in cookie.split(";") if "=" in part).get("DedeUserID")
    current = [x for x in envs.get("data") or [] if x.get("name", "").startswith("BiliBiliCookies__")]
    def same_account(item):
        fields = dict(part.strip().split("=", 1) for part in item.get("value", "").split(";") if "=" in part)
        return fields.get("DedeUserID") == uid
    old = next((x for x in current if same_account(x)), None)
    if old:
        payload = {"id": old["id"], "name": old["name"], "value": cookie,
                   "remarks": old.get("remarks") or "bili-" + str(uid)}
        result = open_json(opener, base + "/open/envs", "PUT", payload, token)
        name = old["name"]
    else:
        used = [int(x["name"].rsplit("__", 1)[1]) for x in current if x["name"].rsplit("__", 1)[1].isdigit()]
        name = "BiliBiliCookies__" + str(max(used, default=0) + 1)
        result = open_json(opener, base + "/open/envs", "POST", [{"name": name, "value": cookie,
                           "remarks": "bili-" + str(uid)}], token)
    if result.get("code") != 200:
        raise ApiError("青龙 Cookie 写入失败")
    LOG.info("Cookie 已保存到青龙变量 %s", name)
    return True


def qr_login():
    LOG.info("青龙自动保存 Cookie：请配置 Ray_QingLongConfig__ClientId 和 Ray_QingLongConfig__ClientSecret")
    LOG.info("扫码成功后会输出完整 Cookie；自动写入失败时可据此手动添加环境变量")
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    base = "https://passport.bilibili.com"
    generated = open_json(opener, base + "/x/passport-login/web/qrcode/generate")
    if generated.get("code") != 0:
        raise ApiError(generated.get("message") or "生成二维码失败")
    data = generated["data"]
    url = data["url"]
    LOG.info("终端字符二维码（深色背景）：\n%s", terminal_qr(url))
    LOG.info("请使用 B 站客户端扫描二维码：%s", "https://tool.lu/qrcode/basic.html?text=" + quote(url, safe=""))
    LOG.info("二维码内容：%s", url)
    for _ in range(30):
        time.sleep(5)
        poll = open_json(opener, base + "/x/passport-login/web/qrcode/poll?" +
            urlencode({"qrcode_key": data["qrcode_key"], "source": "main_mini"}))
        status = poll.get("data") or {}
        code = status.get("code")
        if code == 0:
            fields = {item.name: item.value for item in jar if item.name in
                ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4", "b_nut", "_uuid")}
            if not {"SESSDATA", "bili_jct", "DedeUserID"} <= fields.keys():
                raise ApiError("扫码成功但响应中缺少必要 Cookie")
            cookie = "; ".join(f"{key}={value}" for key, value in fields.items())
            LOG.info("扫码账号 UID：%s", fields["DedeUserID"])
            LOG.info("扫码提取的完整 Cookie：%s", cookie)
            try:
                from bili_qinglong import Client
                from bili_device import ensure_device
                session = Client(cookie)
                ensure_device(session)
                if session.cookie != cookie:
                    cookie = session.cookie
                    LOG.info("设备建档后的完整 Cookie：%s", cookie)
            except Exception as exc:
                LOG.warning("扫码后设备建档失败（%s）；继续使用扫码提取的 Cookie", type(exc).__name__)
            try:
                if save_qinglong(cookie):
                    LOG.info("青龙环境变量已自动写入")
                    return 0
            except Exception as exc:
                LOG.warning("青龙自动写入失败（%s）；请使用上方 Cookie 手动保存", type(exc).__name__)
            LOG.warning("未自动写入青龙环境变量；请使用上方 Cookie 手动保存为 BiliBiliCookies__N")
            return 0
        if code == 86038:
            raise ApiError("二维码已过期")
        LOG.info("等待扫码：%s", status.get("message", ""))
    raise ApiError("扫码超时")
