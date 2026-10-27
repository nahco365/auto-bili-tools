#!/usr/bin/env python3
# cron: 0 15 * * * bili_qinglong.py
"""Qinglong entry point for the BiliBiliToolPro daily workflows.

Python 3.9+; standard library only. See PYTHON_QINGLONG.md for configuration.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import random
import re
import sys
from pathlib import Path
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


LOG = logging.getLogger("bili")
RUN_FAILURES = []
API = "https://api.bilibili.com"
LIVE = "https://api.live.bilibili.com"
MANGA = "https://manga.bilibili.com"
MIXIN_KEY_ENC_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48,
    7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54,
    21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def setting(name, default=""):
    return os.environ.get("Ray_" + name, os.environ.get(name, default))


def boolean(name, default=False):
    return setting(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def integer(name, default):
    try:
        return int(setting(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} 必须是整数") from None


def cookies():
    found = []
    for key, value in os.environ.items():
        match = re.fullmatch(r"BiliBiliCookies__(\d+)", key, re.I)
        if match and value.strip():
            found.append((int(match.group(1)), value.strip()))
    chosen = dict(found)
    fallback = os.environ.get("BILI_COOKIE", "").strip()
    if not chosen and fallback:
        chosen[0] = fallback
    return [(number, value) for number, value in sorted(chosen.items())]


class ApiError(Exception):
    def __init__(self, message, code=None):
        super().__init__(f"{message} ({code})" if code is not None else message)
        self.code = code


@dataclass
class Video:
    aid: int
    bvid: str
    cid: int = 0
    duration: int = 15
    title: str = ""
    copyright: int = 1


class Client:
    def __init__(self, cookie):
        self.cookie = cookie
        self.fields = dict(item.strip().split("=", 1) for item in cookie.split(";") if "=" in item)
        self.csrf = self.fields.get("bili_jct", "")
        self.uid = self.fields.get("DedeUserID", "")
        if not self.fields.get("SESSDATA") or not self.csrf or not self.uid.isdigit():
            raise ValueError("Cookie 需要 SESSDATA、bili_jct 和数字 DedeUserID")
        for name, key in (("Buvid3", "buvid3"), ("Buvid4", "buvid4"), ("BNut", "b_nut")):
            pinned = setting("DeviceCookie__" + name)
            if pinned:
                self.fields[key] = pinned
        self.cookie = "; ".join(f"{key}={value}" for key, value in self.fields.items())
        proxy = setting("Security__WebProxy")
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), ProxyHandler({"https": proxy, "http": proxy}) if proxy else ProxyHandler({}))
        self.interval = max(0, integer("Security__IntervalSecondsBetweenRequestApi", 10))
        self.last_request = 0.0
        self.mixin_key = ""

    def request(self, base, path, params=None, form=None, referer="https://www.bilibili.com/", json_body=None):
        method = "POST" if form is not None or json_body is not None else "GET"
        interval_methods = {part.strip().upper() for part in setting("Security__IntervalMethodTypes", "GET,POST").split(",")}
        paced = method in interval_methods
        if paced and self.last_request and self.interval:
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        url = base + path
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        host = urlsplit(base).hostname
        origin = "https://" + ("live.bilibili.com" if host == "api.live.bilibili.com" else host)
        headers = {
            "User-Agent": (setting("Security__UserAgentApp") or "Mozilla/5.0 (Linux; Android 12) BiliApp/7760700") if base == MANGA else (setting("Security__UserAgent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
            "Cookie": self.cookie, "Referer": referer, "Origin": origin,
            "Accept": "application/json, text/plain, */*",
        }
        body = json.dumps(json_body).encode() if json_body is not None else (urlencode(form).encode() if form is not None else None)
        if body is not None:
            headers["Content-Type"] = "application/json" if json_body is not None else "application/x-www-form-urlencoded; charset=UTF-8"
        req = Request(url, data=body, headers=headers, method=method)
        if paced:
            self.last_request = time.monotonic()
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            if not raw:
                raise ApiError(f"HTTP {exc.code}: {path}") from exc
        except (URLError, TimeoutError) as exc:
            raise ApiError(f"网络请求失败: {path}: {exc}") from exc
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError(f"接口返回非 JSON: {path}") from exc
        if not isinstance(result, dict):
            raise ApiError(f"接口返回格式不正确: {path}")
        code = result.get("code", 0)
        if code != 0:
            raise ApiError(result.get("message") or result.get("msg") or path, code)
        return result.get("data", {})

    def get(self, path, params=None, base=API, referer="https://www.bilibili.com/"):
        return self.request(base, path, params=params, referer=referer)

    def post(self, path, form=None, base=API, params=None, referer="https://www.bilibili.com/"):
        return self.request(base, path, params=params, form=form or {}, referer=referer)

    def post_json(self, path, body, base=API, params=None, referer="https://www.bilibili.com/"):
        return self.request(base, path, params=params, json_body=body, referer=referer)

    def wbi(self, params):
        if not self.mixin_key:
            nav = self.get("/x/web-interface/nav")
            urls = nav.get("wbi_img", {})
            key = "".join(urlsplit(urls.get(part, "")).path.rsplit("/", 1)[-1].split(".")[0] for part in ("img_url", "sub_url"))
            if len(key) < 64:
                raise ApiError("无法获取 WBI 密钥")
            self.mixin_key = "".join(key[i] for i in MIXIN_KEY_ENC_TAB)[:32]
        signed = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in params.items()
                  if k not in ("wts", "w_rid")}
        signed["wts"] = str(int(time.time()))
        query = "&".join(f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted(signed.items()))
        result = dict(params)
        result["wts"] = signed["wts"]
        result["w_rid"] = hashlib.md5((query + self.mixin_key).encode()).hexdigest()
        return result


def step(name, func):
    try:
        func()
        return True
    except ApiError as exc:
        LOG.warning("%s：%s", name, exc)
        RUN_FAILURES.append(f"{name}：{exc}")
    except (ValueError, KeyError, TypeError) as exc:
        LOG.warning("%s：数据异常：%s", name, exc)
        RUN_FAILURES.append(f"{name}：数据异常")
    return False


def user_info(client):
    data = client.get("/x/web-interface/nav")
    if not data.get("isLogin"):
        raise ApiError("Cookie 已失效")
    LOG.info("用户：%s，等级：Lv%s，硬币：%s", data.get("uname"), (data.get("level_info") or {}).get("current_level"), data.get("money"))
    return data


def vip_type(user):
    return int(user.get("vipType") or 0) if int(user.get("vipStatus") or 0) == 1 else 0


def random_video(client):
    up_ids = [x.strip() for x in setting("DailyTaskConfig__SupportUpIds").split(",") if x.strip().isdigit() and int(x) > 0]
    random.shuffle(up_ids)
    if client.uid:
        try:
            relations = client.get("/x/relation/followings", {"vmid": client.uid, "order_type": "attention",
                "pn": 1, "ps": 20, "order": "desc", "jsonp": "jsonp"})
            others = [str(item.get("mid")) for item in relations.get("list") or [] if item.get("mid")]
            random.shuffle(others)
            up_ids.extend(x for x in others if x not in up_ids)
        except ApiError as exc:
            LOG.warning("获取关注列表失败：%s", exc)
    for mid in up_ids:
        try:
            result = client.get("/x/space/wbi/arc/search", client.wbi({"mid": mid, "pn": 1, "ps": 30}))
            items = ((result.get("list") or {}).get("vlist") or [])
            if items:
                item = random.choice(items)
                detail = client.get("/x/web-interface/wbi/view", client.wbi({"bvid": item["bvid"]}))
                return Video(int(detail["aid"]), detail["bvid"], int(detail["cid"]), int(detail.get("duration") or 15), detail.get("title", ""), int(detail.get("copyright") or 1))
        except (ApiError, KeyError, ValueError):
            LOG.warning("UP %s 的视频不可用，尝试其他来源", mid)
    result = client.get("/x/web-interface/ranking/v2", {"rid": 0, "type": "all"})
    items = result.get("list") or []
    if not items:
        raise ApiError("排行榜没有可用视频")
    item = random.choice(items)
    return Video(int(item["aid"]), item["bvid"], int(item["cid"]), int(item.get("duration") or 15), item.get("title", ""), int(item.get("copyright") or 1))


def heartbeat(client, video, played):
    payload = {"aid": video.aid, "bvid": video.bvid, "cid": video.cid, "mid": client.uid,
               "csrf": client.csrf, "played_time": played, "real_played_time": played,
               "realtime": played, "start_ts": int(time.time()), "type": 3, "dt": 2, "play_type": 3}
    client.post("/x/click-interface/web/heartbeat", payload, params={"aid": video.aid, "played_time": played})


def daily(client, user):
    if not boolean("DailyTaskConfig__IsEnable", True) or boolean("Security__IsSkipDailyTask"):
        return
    try:
        status = client.get("/x/member/web/exp/reward", referer="https://account.bilibili.com/account/home")
    except ApiError:
        try:
            status = client.get("/x/member/web/exp/reward", referer="https://account.bilibili.com/account/home")
        except ApiError as exc:
            LOG.warning("每日任务状态获取失败，跳过观看和分享：%s", exc)
            status = None
    want_watch = status is not None and boolean("DailyTaskConfig__IsWatchVideo", True) and not status.get("watch")
    want_share = status is not None and boolean("DailyTaskConfig__IsShareVideo", True) and not status.get("share")
    if want_watch or want_share:
        try:
            video = random_video(client)
        except (ApiError, ValueError, KeyError) as exc:
            LOG.warning("选取视频失败，继续执行投币和大会员任务：%s", exc)
            video = None
    else:
        video = None
    if video is not None:
        LOG.info("视频：%s", video.title)
        opened = False
        if want_watch:
            def watch():
                nonlocal opened
                heartbeat(client, video, 0)
                opened = True
                heartbeat(client, video, random.randint(1, max(1, min(video.duration, 15))))
                LOG.info("观看视频：成功")
            step("观看视频", watch)
        if want_share:
            def share():
                if not opened:
                    heartbeat(client, video, 0)
                client.post("/x/web-interface/share/add", {"aid": video.aid, "csrf": client.csrf,
                    "eab_x": 1, "ramval": random.randint(3, 19), "source": "web_normal", "ga": 1})
                LOG.info("分享视频：成功")
            step("分享视频", share)
    stop_level = integer("DailyTaskConfig__CoinDonationStopLevel", 0)
    if stop_level <= 0 and boolean("DailyTaskConfig__SaveCoinsWhenLv6"):
        stop_level = 6
    level = (user.get("level_info") or {}).get("current_level", 0)
    if stop_level and level >= stop_level:
        LOG.info("达到 Lv%s，跳过投币", stop_level)
    else:
        step("投币", lambda: donate_coins(client, user))
    step("大会员权益", lambda: vip_privilege(client, user))


def donate_coins(client, user):
    target = max(0, min(5, integer("DailyTaskConfig__NumberOfCoins", 5)))
    if not target:
        return
    earned = client.get("/x/web-interface/coin/today/exp")
    already = int(earned or 0) // 10
    balance_info = client.get("/site/getCoin", base="https://account.bilibili.com",
        referer="https://account.bilibili.com/account/coin")
    balance = float(balance_info.get("money") or 0)
    protected = max(0, integer("DailyTaskConfig__NumberOfProtectedCoins", 0))
    needed = min(max(0, target - already), max(0, math.floor(balance - protected)))
    LOG.info("今日已投 %s，目标 %s，可投 %s", already, target, needed)
    if not needed:
        return
    if boolean("DailyTaskConfig__IsDonateCoinForArticle"):
        spent = donate_articles(client, needed)
        needed -= spent
        if needed <= 0:
            return
        LOG.info("专栏投币未完成，剩余 %s 枚转为视频投币", needed)
    success, attempted = 0, set()
    for _ in range(10):
        if success >= needed:
            break
        video = random_video(client)
        if video.aid in attempted or video.copyright != 1:
            continue
        attempted.add(video.aid)
        try:
            donated = client.get("/x/web-interface/archive/coins", {"aid": video.aid}).get("multiply", 0)
            if int(donated) > 0:
                continue
            client.post("/x/web-interface/coin/add", {"aid": video.aid, "multiply": 1,
                "select_like": int(boolean("DailyTaskConfig__SelectLike", True)), "cross_domain": "true",
                "csrf": client.csrf, "eab_x": 2, "ramval": 3, "source": "web_normal", "ga": 1},
                referer=f"https://www.bilibili.com/video/{video.bvid}/")
            success += 1
            LOG.info("投币成功：%s (%s/%s)", video.title, success, needed)
        except ApiError as exc:
            LOG.warning("投币失败：%s", exc)
            if exc.code in (-403, -412):
                break
    LOG.info("本次投币：%s/%s", success, needed)
    if success < needed:
        RUN_FAILURES.append(f"视频投币不足：{success}/{needed}")


def donate_articles(client, needed):
    up_ids = [x.strip() for x in setting("DailyTaskConfig__SupportUpIds").split(",")
              if x.strip().isdigit() and int(x) > 0 and x.strip() != client.uid]
    if not up_ids:
        return 0
    spent, seen = 0, set()
    for _ in range(11):
        if spent >= needed:
            break
        mid = random.choice(up_ids)
        base_params = {"mid": mid, "pn": 1, "ps": 12, "sort": "publish_time",
                       "web_location": 1550101, "platform": "web"}
        try:
            summary = client.get("/x/space/wbi/article", client.wbi(base_params))
            count = int(summary.get("count") or 0)
            if not count:
                continue
            params = {**base_params, "pn": random.randint(1, max(1, math.ceil(count / 12)))}
            articles = client.get("/x/space/wbi/article", client.wbi(params)).get("articles") or []
            if not articles:
                continue
            article = random.choice(articles)
            cvid = int(article["id"])
            if cvid in seen:
                continue
            seen.add(cvid)
            info = client.get("/x/article/viewinfo", {"id": cvid})
            if int(info.get("coin") or 0) > 0:
                continue
            client.post("/x/web-interface/coin/add", {"aid": cvid, "upid": mid,
                "multiply": 1, "avtype": 2, "csrf": client.csrf},
                referer=f"https://www.bilibili.com/read/cv{cvid}/")
            spent += 1
            LOG.info("专栏投币成功：%s (%s/%s)", article.get("title"), spent, needed)
            if boolean("DailyTaskConfig__SelectLike", True):
                step("专栏点赞", lambda: client.post("/x/article/like", params={
                    "id": cvid, "type": 1, "csrf": client.csrf}))
        except (ApiError, KeyError, ValueError) as exc:
            LOG.warning("专栏投币尝试失败：%s", exc)
    return spent


def vip_privilege(client, user):
    if not boolean("VipPrivilegeConfig__IsEnable", True) or vip_type(user) != 2:
        return
    for kind in (1, 2):
        step(f"领取大会员权益 {kind}", lambda kind=kind: client.post("/x/vip/privilege/receive", params={"type": kind, "csrf": client.csrf}))


def live_sign(client, _user):
    try:
        data = client.get("/xlive/web-ucenter/v1/sign/DoSign", base=LIVE, referer="https://link.bilibili.com/")
        LOG.info("直播签到：%s %s", data.get("text", "成功"), data.get("specialText", ""))
    except ApiError as exc:
        LOG.info("直播签到未完成：%s", exc)


def manga(client, _user):
    if not boolean("MangaTaskConfig__IsEnable", True):
        return
    platform = setting("DailyTaskConfig__DevicePlatform", "android")
    def manga_sign():
        try:
            client.post("/twirp/activity.v1.Activity/ClockIn", base=MANGA, params={"platform": platform})
        except ApiError as exc:
            if any(marker in str(exc).lower() for marker in ("不能重复签到", "已签到", "duplicate", "already signed")):
                LOG.info("漫画今日已签到")
                return
            raise
    step("漫画签到", manga_sign)
    comic_id = integer("MangaTaskConfig__CustomComicId", 27355)
    ep_id = integer("MangaTaskConfig__CustomEpId", 381662)
    if comic_id > 0 and ep_id > 0:
        step("漫画阅读", lambda: client.post("/twirp/bookshelf.v1.Bookshelf/AddHistory", base=MANGA,
             params={"platform": platform, "comic_id": comic_id, "ep_id": ep_id}))


def manga_privilege(client, user):
    if boolean("MangaPrivilegeTaskConfig__IsEnable", True) and vip_type(user):
        data = client.post("/twirp/user.v1.User/GetVipReward", base=MANGA, params={"reason_id": 1})
        LOG.info("漫画大会员权益：领取 %s 张漫读券", data.get("amount", "?"))


def silver2coin(client, _user):
    if not boolean("Silver2CoinTaskConfig__IsEnable", True):
        return
    data = client.get("/xlive/revenue/v1/wallet/getStatus", base=LIVE, referer="https://link.bilibili.com/")
    LOG.info("银瓜子：%s；今日剩余兑换：%s", data.get("silver"), data.get("silver_2_coin_left"))
    if int(data.get("silver_2_coin_left") or 0) > 0:
        visit_id = str(random.randint(1, 9)) + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10)) + "0"
        client.post("/xlive/revenue/v1/wallet/silver2coin", {"csrf": client.csrf,
                    "csrf_token": client.csrf, "visit_id": visit_id}, base=LIVE,
                    referer="https://link.bilibili.com/")
        LOG.info("银瓜子兑换硬币：成功")


def charge(client, user):
    if not boolean("ChargeTaskConfig__IsEnable", True) or vip_type(user) != 2:
        return
    up_id = setting("ChargeTaskConfig__AutoChargeUpId__" + client.uid).strip()
    account_count = int(os.getenv("BILI_ACCOUNT_COUNT") or len(cookies()))
    if not up_id and account_count == 1:
        up_id = setting("ChargeTaskConfig__AutoChargeUpId").strip()
    if not up_id or up_id == "-1":
        LOG.info("账号 UID %s 未配置充电目标，跳过", client.uid)
        return
    if not up_id.isdigit() or int(up_id) <= 0:
        raise ValueError("充电目标必须是正整数 UID")
    coupon = float((user.get("wallet") or {}).get("coupon_balance") or 0)
    if coupon < 2:
        LOG.info("B 币券余额不足 2，跳过充电")
        return
    data = client.post("/x/ugcpay/web/v2/trade/elec/pay/quick", {
        "bp_num": coupon, "is_bp_remains_prior": "true", "up_mid": up_id,
        "otype": "up", "oid": up_id, "csrf": client.csrf})
    if int(data.get("status") or 0) != 4:
        raise ApiError("充电未确认成功")
    LOG.info("向 UID %s 充电 %s B 币成功", up_id, coupon)
    order = data.get("order_no")
    if order:
        comment = setting("ChargeTaskConfig__ChargeComment") or random.choice(["支持~", "UP加油!", "干杯"])
        step("充电留言", lambda: client.post("/x/ugcpay/trade/elec/message", {
            "order_id": order, "message": comment, "csrf": client.csrf}))


def unfollow_batched(client, _user):
    if not boolean("UnfollowBatchedTaskConfig__IsEnable", True):
        return
    group = setting("UnfollowBatchedTaskConfig__GroupName", "天选时刻")
    count = integer("UnfollowBatchedTaskConfig__Count", 20)
    if count == 0:
        LOG.info("取关数量为 0，跳过")
        return
    tags = client.get("/x/relation/tags", {"jsonp": "jsonp"}, referer=f"https://space.bilibili.com/{client.uid}/fans/follow")
    tag = next((item for item in tags if item.get("name") == group), None)
    if not tag:
        LOG.info("关注分组不存在：%s", group)
        return
    total = int(tag.get("count") or 0)
    if count == -1:
        count = total
    count = min(max(0, count), total)
    retained = set(setting("UnfollowBatchedTaskConfig__RetainUids").split(","))
    candidates = []
    for page in range(math.ceil(total / 20), 0, -1):
        users = client.get("/x/relation/tag", {"mid": client.uid, "tagid": tag["tagid"],
            "pn": page, "ps": 20, "jsonp": "jsonp"}, referer=f"https://space.bilibili.com/{client.uid}/fans/follow")
        candidates.extend(reversed(users or []))
        if len(candidates) >= count:
            break
    success = 0
    for item in candidates[:count]:
        uid = str(item.get("mid") or "")
        if not uid or uid in retained:
            continue
        try:
            client.post("/x/relation/modify", {"fid": uid, "csrf": client.csrf,
                "act": 2, "re_src": 11, "jsonp": "jsonp"},
                referer=f"https://space.bilibili.com/{client.uid}/fans/follow")
            success += 1
        except ApiError as exc:
            LOG.warning("取关 UID %s 失败：%s", uid, exc)
    LOG.info("分组 %s：已取关 %s/%s", group, success, count)


def following_ids(client):
    data = client.get("/x/relation/followings", {"vmid": client.uid, "order_type": "",
        "pn": 1, "ps": 20, "order": "desc", "jsonp": "jsonp"},
        referer=f"https://space.bilibili.com/{client.uid}/fans/follow")
    return [int(item["mid"]) for item in data.get("list") or []]


def lottery(client, _user):
    if not boolean("LiveLotteryTaskConfig__IsEnable", True):
        return
    auto_group = boolean("LiveLotteryTaskConfig__AutoGroupFollowings", True)
    before = following_ids(client) if auto_group else []
    denied = set(setting("LiveLotteryTaskConfig__DenyUids", "65566781,1277481241,1643654862,603676925").replace(" ", "").split(","))
    include = [x for x in setting("LiveLotteryTaskConfig__IncludeAwardNames").split("|") if x]
    exclude = [x for x in setting("LiveLotteryTaskConfig__ExcludeAwardNames", "舰|船|航海|代金券|自拍|照|写真|图|提督").split("|") if x]
    areas = client.get("/xlive/web-interface/v1/index/getWebAreaList", {"source_id": 2}, base=LIVE)
    followed = set()
    seen_rooms = set()
    for area in areas.get("data") or []:
        for page in (1, 2, 3):
            try:
                result = client.get("/room/v3/area/getRoomList", {"platform": "web",
                    "parent_area_id": area["id"], "area_id": 0, "sort_type": "online",
                    "page": page, "page_size": 99}, base=LIVE,
                    referer="https://live.bilibili.com/")
            except ApiError as exc:
                LOG.warning("分区 %s 第 %s 页失败：%s", area.get("name"), page, exc)
                break
            rooms = result.get("list") or []
            for room in rooms:
                pendant = room.get("pendant_info")
                if not isinstance(pendant, dict) or not isinstance(pendant.get("2"), dict):
                    continue
                if pendant["2"].get("pendent_id") not in (504, 1432):
                    continue
                room_id = room.get("roomid")
                if not room_id or room_id in seen_rooms or str(room.get("uid")) in denied:
                    continue
                seen_rooms.add(room_id)
                try:
                    info = client.get("/xlive/lottery-interface/v1/Anchor/Check",
                        {"roomid": room_id}, base=LIVE)
                    award = info.get("award_name") or ""
                    if int(info.get("status") or 0) != 1 or any(x in award for x in exclude):
                        continue
                    if include and not any(x in award for x in include):
                        continue
                    if int(info.get("gift_price") or 0) > 0 or int(info.get("require_type") or 0) not in (0, 1):
                        continue
                    visit_id = str(random.randint(1, 9)) + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10)) + "0"
                    client.post("/xlive/lottery-interface/v1/Anchor/Join", {
                        "id": info["id"], "gift_id": info.get("gift_id", 0),
                        "gift_num": info.get("gift_num", 0), "csrf": client.csrf,
                        "csrf_token": client.csrf, "visit_id": visit_id, "platform": "pc"},
                        base=LIVE, referer=f"https://live.bilibili.com/{room_id}")
                    LOG.info("天选参与成功：%s / %s", room.get("uname"), award)
                    if int(info.get("require_type") or 0) == 1:
                        followed.add(int(room["uid"]))
                except (ApiError, KeyError, ValueError) as exc:
                    LOG.warning("直播间 %s 参与失败：%s", room_id, exc)
            if len(rooms) < 99:
                break
    if auto_group and followed:
        after = following_ids(client)
        last = before[0] if before else None
        newly_followed = set(after[:after.index(last)] if last in after else after)
        targets = followed & newly_followed
        if targets:
            tags = client.get("/x/relation/tags", {"jsonp": "jsonp"})
            tag = next((x for x in tags if x.get("name") == "天选时刻"), None)
            if tag:
                tag_id = tag["tagid"]
            else:
                created = client.post("/x/relation/tag/create", {"tag": "天选时刻", "csrf": client.csrf})
                tag_id = created["tagid"]
            client.post("/x/relation/tags/copyUsers", {"fids": ",".join(map(str, sorted(targets))),
                "tagids": tag_id, "csrf": client.csrf, "jsonp": "jsonp"})
            LOG.info("天选新增关注分组：%s 人", len(targets))


def app_params(client):
    now = int(time.time() * 1000)
    return {"build": "8451100", "disable_rcmd": 0, "mobi_app": "android",
        "platform": "android", "statistics": '{"appId":1,"platform":3,"version":"8.45.1","abtest":""}',
        "t": now, "ts": now // 1000, "csrf": client.csrf, "buvid": client.fields.get("buvid3", ""),
        "brand": "Samsung", "channel": "bili", "containerName": "AbstractWebActivity", "device": "phone"}


def vip_combine(client):
    return client.get("/x/vip_point/task/combine", app_params(client),
        referer="https://big.bilibili.com/mobile/bigPoint/task")


def vip_tasks(combine):
    for module in (combine.get("task_info") or {}).get("modules") or []:
        for task in module.get("common_task_item") or []:
            yield task


def vip_big_point(client, user):
    if not boolean("VipBigPointConfig__IsEnable", True) or vip_type(user) == 0:
        return
    referer = "https://big.bilibili.com/mobile/bigPoint/task"
    def experience():
        data = client.get("/x/vip/privilege/my", referer=referer)
        state = next((item.get("state") for item in data.get("list") or [] if item.get("type") == 9), None)
        if state == 0:
            client.post("/x/vip/experience/add", {"csrf": client.csrf}, referer=referer)
            LOG.info("大会员经验领取成功")
        elif state == 2:
            LOG.info("大会员经验需先完成视频观看任务")
    step("大会员经验", experience)
    def sign():
        sign_info = client.get("/x/vip/vip_center/sign_in/three_days_sign", app_params(client), referer=referer)
        if (sign_info.get("three_day_sign") or {}).get("signed"):
            return
        now = int(time.time() * 1000)
        client.post_json("/pgc/activity/score/task/sign2", {"device": "phone", "t": now, "ts": now // 1000},
            params={"mobi_app": "android", "csrf": client.csrf, "platform": "android"},
            referer="https://big.bilibili.com/mobile/index")
        LOG.info("大会员积分签到成功")
    step("大会员积分签到", sign)
    combine = vip_combine(client)
    LOG.info("当前大会员积分：%s", (combine.get("point_info") or {}).get("point"))
    available = {task.get("task_code"): task for task in vip_tasks(combine)}
    # The .NET workflow claims all unclaimed daily missions first.
    for code, task in available.items():
        if task.get("state") == 0:
            step(f"领取积分任务 {code}", lambda code=code: client.post("/pgc/activity/score/task/receive/v2",
                {"TaskCode": code}, referer=referer))
    for code in ("bonus", "privilege", "dress-view", "vipmallview", "animatetab", "filmtab", "ogvwatchnew"):
        task = available.get(code)
        if not task or task.get("state") == 3:
            continue
        def complete(code=code):
            if code in ("bonus", "privilege"):
                client.post_json("/pgc/activity/score/task/complete", {"TaskCode": code}, referer=referer)
            elif code == "vipmallview":
                client.post_json("/api/activity/fire/common/event/dispatch",
                    {"Csrf": client.csrf, "EventId": "hevent_oy4b7h3epeb"},
                    base="https://show.bilibili.com", referer=referer)
            elif code in ("animatetab", "filmtab"):
                time.sleep(10)
                position = "jp_channel" if code == "animatetab" else "tv_channel"
                client.post("/pgc/activity/deliver/task/complete", {**app_params(client),
                    "position": position, "c_locale": "zh_CN", "s_locale": "zh_CN"}, referer=referer)
            else:
                client.post("/pgc/activity/score/task/complete/v2", {"TaskCode": code}, referer=referer)
            LOG.info("大会员积分任务 %s：已提交", code)
        step(f"大会员积分任务 {code}", complete)
    refreshed = vip_combine(client)
    LOG.info("任务后大会员积分：%s", (refreshed.get("point_info") or {}).get("point"))


sys.modules.setdefault("bili_qinglong", sys.modules[__name__])


def live_fans_medal(client, user):
    from bili_medal import live_fans_medal as run_medal
    return run_medal(client, user)


def test_cookie(client, user):
    LOG.info("Cookie 有效：UID %s，用户名 %s", client.uid, user.get("uname"))


TASKS = {"Daily": daily, "LiveSign": live_sign, "Manga": manga,
         "MangaPrivilege": manga_privilege, "Silver2Coin": silver2coin,
         "VipPrivilege": vip_privilege, "Charge": charge,
         "UnfollowBatched": unfollow_batched, "LiveLottery": lottery,
         "VipBigPoint": vip_big_point, "LiveFansMedal": live_fans_medal,
         "Test": test_cookie, "CookieTest": test_cookie}


def main(argv=None):
    parser = argparse.ArgumentParser(description="BiliBiliToolPro Python 青龙任务")
    parser.add_argument("tasks", nargs="*", help="任务名；默认 Daily LiveSign Manga MangaPrivilege Silver2Coin")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
    selected = args.tasks or setting("RunTasks", "Daily&LiveSign&Manga&MangaPrivilege&Silver2Coin").replace(",", "&").split("&")
    selected = [name.strip() for name in selected if name.strip()]
    unknown = set(selected) - set(TASKS) - {"Login"}
    if unknown:
        parser.error("不支持的任务：" + ", ".join(sorted(unknown)))
    if "Login" in selected:
        try:
            from bili_login import qr_login
            qr_login()
        except ApiError as exc:
            LOG.error("扫码登录失败：%s", exc)
            return 1
        selected = [name for name in selected if name != "Login"]
        if not selected:
            return 0
    accounts = cookies()
    if not accounts:
        LOG.error("未找到 BiliBiliCookies__N 环境变量")
        return 2
    failed = False
    RUN_FAILURES.clear()
    random_sleep = max(0, integer("Security__RandomSleepMaxMin", 0))
    if random_sleep:
        minutes = random.uniform(0, random_sleep)
        LOG.info("随机等待 %.1f 分钟", minutes)
        time.sleep(minutes * 60)
    for number, cookie in accounts:
        LOG.info("===== 账号 %s =====", number)
        try:
            client = Client(cookie)
            try:
                from bili_device import ensure_device
                if ensure_device(client):
                    cookie_output = os.getenv("BILI_COOKIE_OUTPUT")
                    if cookie_output:
                        Path(cookie_output).write_text(client.cookie, encoding="utf-8")
                    else:
                        from bili_login import save_qinglong
                        if not save_qinglong(client.cookie):
                            LOG.warning("设备 Cookie 仅在本次任务有效；请配置青龙 OpenAPI 以持久保存")
            except (ApiError, OSError, ValueError) as exc:
                LOG.warning("设备 Cookie 建档失败：%s", exc)
            user = user_info(client)
        except (ApiError, ValueError) as exc:
            LOG.error("账号 %s 登录失败：%s", number, exc)
            failed = True
            continue
        for name in selected:
            LOG.info("--- %s ---", name)
            try:
                TASKS[name](client, user)
            except (ApiError, ValueError, KeyError, TypeError) as exc:
                LOG.error("账号 %s 的 %s 失败：%s", number, name, exc)
                failed = True
    if RUN_FAILURES:
        LOG.warning("本次有 %s 个子任务失败", len(RUN_FAILURES))
    return 1 if failed or RUN_FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
