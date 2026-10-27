"""Today task status evaluation for the Web dashboard."""

from datetime import datetime, timedelta

from bili_qinglong import ApiError, Client, vip_type
from python_port.scheduler import last_fire_today


DAILY_ITEMS = (("Login", "每日登录", "login"), ("Watch", "观看视频", "watch"),
               ("Share", "分享视频", "share"), ("DonateCoin", "投币", "coins"),
               ("VipPrivilege", "会员权益", None))


def _enabled(settings, section):
    return settings.get(section + ":IsEnable", "true").lower() == "true"


def _daily_enabled(settings, key):
    if key == "Watch":
        return settings.get("DailyTaskConfig:IsWatchVideo", "true").lower() == "true"
    if key == "Share":
        return settings.get("DailyTaskConfig:IsShareVideo", "true").lower() == "true"
    if key == "DonateCoin":
        return int(settings.get("DailyTaskConfig:NumberOfCoins", "5")) > 0
    if key == "VipPrivilege":
        return _enabled(settings, "VipPrivilegeConfig")
    return True


def probe_account(cookie):
    client = Client(cookie)
    client.interval = 0
    nav = client.get("/x/web-interface/nav")
    if not nav.get("isLogin"):
        return {"valid": False, "name": None, "level": None, "reward": None, "coin_exp": None}
    try:
        reward = client.get("/x/member/web/exp/reward", referer="https://account.bilibili.com/account/home")
    except ApiError:
        reward = None
    try:
        coin_exp = client.get("/x/web-interface/coin/today/exp")
    except ApiError:
        coin_exp = None
    return {"valid": True, "name": nav.get("uname"),
            "level": (nav.get("level_info") or {}).get("current_level"),
            "vip_type": vip_type(nav), "reward": reward, "coin_exp": int(coin_exp) if coin_exp is not None else None}


def build_today(store, probe=False):
    settings = store.settings()
    schedules = store.schedules()
    records = {}
    for row in store.today_records():
        records.setdefault((row["uid"], row["task"]), row)
    now = datetime.now()
    result = []
    for account in store.accounts():
        profile = None
        if probe:
            try:
                profile = probe_account(account["cookie"])
            except (ApiError, ValueError, KeyError, TypeError):
                profile = {"valid": False, "name": None, "reward": None, "coin_exp": None}
        groups = []
        for schedule in schedules:
            task = schedule["task"]
            section = {"Daily": "DailyTaskConfig", "Manga": "MangaTaskConfig",
                       "MangaPrivilege": "MangaPrivilegeTaskConfig", "Silver2Coin": "Silver2CoinTaskConfig",
                       "Charge": "ChargeTaskConfig", "VipPrivilege": "VipPrivilegeConfig",
                       "VipBigPoint": "VipBigPointConfig", "LiveLottery": "LiveLotteryTaskConfig",
                       "LiveFansMedal": "LiveFansMedalTaskConfig", "UnfollowBatched": "UnfollowBatchedTaskConfig"}.get(task)
            enabled = bool(schedule["enabled"]) and (not section or _enabled(settings, section))
            row = records.get((account["uid"], task))
            try:
                latest = last_fire_today(schedule["cron"], now.date().isoformat(), now.replace(second=0, microsecond=0).isoformat())
            except ValueError:
                latest = None
            due = latest is not None and now >= latest + timedelta(minutes=10)
            if not enabled:
                status = "Disabled"
            elif row:
                status = row["status"]
            elif due:
                status = "NotDone"
            else:
                status = "Pending"
            items = []
            if task == "Daily":
                for key, label, reward_field in DAILY_ITEMS:
                    if not _daily_enabled(settings, key):
                        item_status = "Disabled"
                    elif profile is None:
                        item_status = "Pending"
                    elif not profile["valid"]:
                        item_status = "Failed"
                    elif reward_field == "coins":
                        target = min(5, int(settings.get("DailyTaskConfig:NumberOfCoins", "5")))
                        item_status = "Pending" if profile["coin_exp"] is None else (
                            "Success" if profile["coin_exp"] // 10 >= target else "NotDone" if due else "Pending")
                    elif reward_field:
                        item_status = "Pending" if profile["reward"] is None else (
                            "Success" if profile["reward"].get(reward_field) else "NotDone" if due else "Pending")
                    else:
                        item_status = status if profile.get("vip_type") == 2 else "Disabled"
                    items.append({"key": key, "label": label, "status": item_status})
            groups.append({"task": task, "status": status, "record": row, "items": items})
        result.append({"account": account, "profile": profile, "groups": groups})
    return result
