"""Task failure notification adapters."""

import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOG = logging.getLogger("bili.notify")


def _post(url, data, json_body=True, headers=None):
    if json_body:
        body = json.dumps(data, ensure_ascii=False).encode()
        content_type = "application/json"
    else:
        body = urlencode(data).encode()
        content_type = "application/x-www-form-urlencoded"
    req = Request(url, data=body, headers={"Content-Type": content_type, **(headers or {})}, method="POST")
    with urlopen(req, timeout=15) as response:
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")


def _get_json(url):
    with urlopen(url, timeout=15) as response:
        return json.load(response)


def send_failure(settings, task, output):
    if settings.get("Notification:FailureEnabled", "false").lower() != "true":
        return
    title = f"BiliBiliToolPro：{task} 失败"
    message = title + "\n" + output[-3000:]
    send_message(settings, title, message)


def send_cookie_expiry(settings, uid):
    if settings.get("Notification:CookieExpiryEnabled", "false").lower() != "true":
        return
    title = "BiliBiliToolPro：B 站 Cookie 已失效"
    send_message(settings, title, f"UID {uid} 的 Cookie 已失效，请重新登录。")


def send_message(settings, title, message):
    channels = []
    webhook = settings.get("Notification:WebhookUrl")
    if webhook:
        channels.append(("Webhook", lambda: _post(webhook, {"title": title, "message": message})))
    bot = settings.get("Notification:TelegramBotToken")
    chat = settings.get("Notification:TelegramChatId")
    if bot and chat:
        channels.append(("Telegram", lambda: _post(f"https://api.telegram.org/bot{bot}/sendMessage",
                                                   {"chat_id": chat, "text": message})))
    server_key = settings.get("Notification:ServerChanKey")
    if server_key:
        channels.append(("ServerChan", lambda: _post(f"https://sctapi.ftqq.com/{server_key}.send",
                                                     {"title": title, "desp": message}, json_body=False)))
    pushplus = settings.get("Notification:PushPlusToken")
    if pushplus:
        channels.append(("PushPlus", lambda: _post("https://www.pushplus.plus/send",
                                                   {"token": pushplus, "title": title, "content": message})))
    gotify_url = settings.get("Notification:GotifyUrl", "").rstrip("/")
    gotify_token = settings.get("Notification:GotifyToken")
    if gotify_url and gotify_token:
        channels.append(("Gotify", lambda: _post(gotify_url + "/message",
                                                 {"title": title, "message": message, "priority": 5},
                                                 headers={"X-Gotify-Key": gotify_token})))
    work_hook = settings.get("Notification:WorkWeixinWebhook")
    if work_hook:
        channels.append(("WorkWeixin", lambda: _post(work_hook,
                        {"msgtype": "markdown", "markdown": {"content": message}})))
    ding_hook = settings.get("Notification:DingTalkWebhook")
    if ding_hook:
        channels.append(("DingTalk", lambda: _post(ding_hook,
                        {"msgtype": "text", "text": {"content": message}})))
    teams_hook = settings.get("Notification:TeamsWebhook")
    if teams_hook:
        channels.append(("Teams", lambda: _post(teams_hook, {"text": message})))
    custom_url = settings.get("Notification:CustomApiUrl")
    if custom_url:
        template = settings.get("Notification:CustomApiBody", '{"message":#msg#}')
        def custom_send():
            data = json.loads(template.replace("#msg#", json.dumps(message, ensure_ascii=False)))
            _post(custom_url, data)
        channels.append(("CustomApi", custom_send))
    corp = settings.get("Notification:WorkWeixinCorpId")
    agent = settings.get("Notification:WorkWeixinAgentId")
    secret = settings.get("Notification:WorkWeixinSecret")
    if corp and agent and secret:
        def work_app_send():
            auth_url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?" + urlencode({"corpid": corp, "corpsecret": secret})
            token_response = _get_json(auth_url)
            if token_response.get("errcode") != 0:
                raise RuntimeError("获取企业微信应用 Token 失败")
            send_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?" + urlencode({"access_token": token_response["access_token"]})
            _post(send_url, {"touser": settings.get("Notification:WorkWeixinToUser") or "@all",
                             "msgtype": "text", "agentid": int(agent), "text": {"content": message}, "safe": 0})
        channels.append(("WorkWeixinApp", work_app_send))
    for name, send in channels:
        try:
            send()
        except Exception as exc:
            LOG.warning("%s 通知失败：%s", name, exc)
