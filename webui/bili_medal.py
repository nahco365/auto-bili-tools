"""Fans medal tasks used by bili_qinglong.py."""

import hashlib
import hmac
import json
import logging
import math
import re
import time
import uuid

from bili_qinglong import ApiError, LIVE, boolean, integer, setting


LOG = logging.getLogger("bili")
TRACE = "https://live-trace.bilibili.com"


def task_plan(data, action):
    item = next((x for x in data.get("task_info") or [] if x.get("jump_type") == action), None)
    if not item or item.get("is_done") or (data.get("is_lighted") and data.get("reach_free_intimacy_limit")):
        return 0, 0
    quantity = re.search(r"\d+(?:\.\d+)?", item.get("title") or "")
    progress = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", item.get("sub_title") or "")
    if not quantity:
        raise ApiError("无法解析粉丝勋章任务要求")
    round_size = math.ceil(float(quantity.group()) * (60 if action == "watchLive" else 1))
    if not 0 < round_size <= 86400:
        raise ApiError("粉丝勋章任务要求超出范围")
    if not progress:
        if not data.get("is_lighted"):
            return round_size, round_size
        raise ApiError("无法解析粉丝勋章任务进度")
    current, total = map(float, progress.groups())
    if total > 1000:
        raise ApiError("粉丝勋章任务进度超出范围")
    return math.ceil(max(0, total - current) * round_size), round_size


def medals(client):
    included = set(setting("LiveFansMedalTaskConfig__IncludedAnchorIds").split(","))
    excluded = set(setting("LiveFansMedalTaskConfig__ExcludedAnchorIds").split(","))
    selected_only = boolean("LiveFansMedalTaskConfig__OnlySelectedAnchors")
    found = {}
    for page in range(1, 1001):
        result = client.get("/xlive/app-ucenter/v1/fansMedal/panel", {"page": page, "page_size": 10}, base=LIVE)
        for item in (result.get("special_list") or []) + (result.get("list") or []):
            anchor = str((item.get("medal") or {}).get("target_id") or "")
            room = (item.get("room_info") or {}).get("room_id")
            if anchor and room and anchor not in excluded and (not selected_only or anchor in included):
                found[anchor] = item
        page_info = result.get("page_info") or {}
        if not page_info.get("has_more") and page >= int(page_info.get("total_page") or 0):
            return list(found.values())
        time.sleep(.5)
    raise ApiError("粉丝勋章分页未完成")


def tasks(client, anchor):
    return client.get("/xlive/app-ucenter/v1/fansMedal/GetActivatedMedalInfo", {
        "target_id": anchor, "csrf": client.csrf, "web_location": "444.260"}, base=LIVE)


def room_info(client, room):
    return client.get("/room/v1/Room/get_info", {"room_id": room, "from": "room"}, base=LIVE)


def interact(client, medal, action, budget):
    anchor = int(medal["medal"]["target_id"])
    room = int(medal["room_info"]["room_id"])
    data = tasks(client, anchor)
    remaining, round_size = task_plan(data, action)
    target = min(remaining, budget)
    sent = 0
    failures = 0
    while sent < target:
        state = room_info(client, room)
        live = int(state.get("live_status") or 0) == 1
        if action == "like" and not live:
            break
        if action == "sendDanmu" and boolean("LiveFansMedalTaskConfig__DanmakuOnlyWhenOffline") and live:
            break
        if action == "sendDanmu" and not data.get("is_lighted") and live and boolean("LiveFansMedalTaskConfig__EnableLike", True):
            break
        amount = min(10, target - sent) if action == "like" else 1
        try:
            if action == "like":
                client.post("/xlive/app-ucenter/v1/like_info_v3/like/likeReportV3", {
                    "click_time": amount, "room_id": room, "uid": client.uid,
                    "anchor_id": anchor, "csrf_token": client.csrf, "csrf": client.csrf}, base=LIVE)
            else:
                client.post("/msg/send", {"bubble": 0, "msg": setting("LiveFansMedalTaskConfig__DanmakuContent", "OvO"),
                    "color": 16777215, "mode": 1, "fontsize": 25, "rnd": int(time.time()),
                    "roomid": room, "csrf": client.csrf, "csrf_token": client.csrf}, base=LIVE)
            sent += amount
            failures = 0
        except ApiError:
            failures += 1
            limit = 3 if action == "like" else max(1, min(10, integer("LiveFansMedalTaskConfig__SendDanmakugiveUpThreshold", 3)))
            if failures >= limit:
                raise
        time.sleep(3 if action == "like" else 7)
        if sent and (sent % max(1, round_size) == 0 or sent >= target):
            data = tasks(client, anchor)
            remaining, round_size = task_plan(data, action)
            if not remaining:
                break
            target = min(target, sent + remaining)
    LOG.info("粉丝勋章 %s：%s 已执行 %s", medal["medal"].get("medal_name"), action, sent)


def signature(text, rules, key):
    algorithms = {0: "md5", 1: "sha1", 2: "sha256", 3: "sha224", 4: "sha512", 5: "sha384"}
    for rule in rules:
        if rule not in algorithms:
            raise ApiError("未知直播心跳签名算法")
        text = hmac.new(key.encode(), text.encode(), algorithms[rule]).hexdigest()
    return text


def watch(client, medal, budget):
    anchor = int(medal["medal"]["target_id"])
    room = int(medal["room_info"]["room_id"])
    remaining, _ = task_plan(tasks(client, anchor), "watchLive")
    target = min(remaining, budget)
    if target <= 0:
        return
    info = room_info(client, room)
    if int(info.get("live_status") or 0) != 1:
        return
    parent, area = int(info["parent_area_id"]), int(info["area_id"])
    live_buvid = client.fields.get("LIVE_BUVID", "")
    device_uuid = str(uuid.uuid4())
    device = json.dumps([live_buvid, device_uuid], separators=(",", ":"))
    ua = setting("Security__UserAgent", "Mozilla/5.0")
    enter = {"id": json.dumps([parent, area, 0, room], separators=(",", ":")),
        "ruid": anchor, "ts": int(time.time() * 1000), "is_patch": 0,
        "heart_beat": "[]", "ua": ua, "csrf_token": client.csrf, "csrf": client.csrf,
        "visit_id": "", "device": device, "web_location": "444.8"}
    state = client.post("/xlive/data-interface/v1/x25Kn/E", client.wbi(enter), base=TRACE)
    elapsed = 0
    sequence = 1
    failures = 0
    while elapsed < target:
        interval = int(state.get("heartbeat_interval") or 0)
        if not 0 < interval <= 300 or not state.get("secret_key"):
            raise ApiError("直播心跳参数无效")
        time.sleep(interval)
        if int(room_info(client, room).get("live_status") or 0) != 1:
            return
        now = int(time.time() * 1000)
        key = state["secret_key"]
        ets = int(state["timestamp"])
        payload = {"platform": "web", "parent_id": parent, "area_id": area, "seq_id": sequence,
            "room_id": room, "buvid": live_buvid, "uuid": device_uuid,
            "ets": ets, "time": interval, "ts": now}
        digest = signature(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), state.get("secret_rule") or [], key)
        form = {"s": digest, "id": json.dumps([parent, area, sequence, room], separators=(",", ":")),
            "ets": ets, "benchmark": key, "time": interval, "ts": now, "ua": ua,
            "csrf_token": client.csrf, "csrf": client.csrf, "visit_id": "",
            "device": device, "ruid": anchor, "trackid": "-99998", "web_location": "444.8"}
        try:
            state = client.post("/xlive/data-interface/v1/x25Kn/X", client.wbi(form), base=TRACE)
            failures = 0
            elapsed += interval
            sequence += 1
        except ApiError:
            failures += 1
            if failures >= max(1, min(10, integer("LiveFansMedalTaskConfig__HeartBeatSendGiveUpThreshold", 5))):
                raise
        if elapsed and (elapsed % 60 < interval or elapsed >= target):
            remaining, _ = task_plan(tasks(client, anchor), "watchLive")
            if not remaining:
                break
    LOG.info("粉丝勋章 %s：观看 %s 秒", medal["medal"].get("medal_name"), elapsed)


def live_fans_medal(client, _user):
    if not boolean("LiveFansMedalTaskConfig__IsEnable", True):
        return
    items = medals(client)
    configs = (("sendDanmu", "EnableDanmaku", "SendDanmakuNumber", 100),
               ("like", "EnableLike", "LikeNumber", 5000),
               ("watchLive", "EnableWatch", "HeartBeatNumber", 86400))
    for action, flag, amount, daily_limit in configs:
        if not boolean("LiveFansMedalTaskConfig__" + flag, True):
            continue
        budget = daily_limit if boolean("LiveFansMedalTaskConfig__FollowDailyTaskLimit") else integer("LiveFansMedalTaskConfig__" + amount, 70 if action == "watchLive" else 30 if action == "like" else 1) * (60 if action == "watchLive" else 1)
        for medal in items:
            try:
                if action == "watchLive":
                    watch(client, medal, budget)
                else:
                    interact(client, medal, action, budget)
            except (ApiError, KeyError, ValueError) as exc:
                LOG.warning("粉丝勋章 %s 的 %s 任务失败：%s", (medal.get("medal") or {}).get("medal_name"), action, exc)
