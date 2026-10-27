"""Read-only fans medal overview for the Web settings page."""

import re
import time

from bili_qinglong import Client, LIVE


def read_medals(cookie):
    client = Client(cookie)
    client.interval = 0
    found = {}
    for page in range(1, 101):
        data = client.get("/xlive/app-ucenter/v1/fansMedal/panel",
                          {"page": page, "page_size": 10}, base=LIVE)
        for item in (data.get("special_list") or []) + (data.get("list") or []):
            medal = item.get("medal") or {}
            anchor = str(medal.get("target_id") or "")
            if anchor and anchor != "0":
                found.setdefault(anchor, item)
        info = data.get("page_info") or {}
        if not info.get("has_more") and page >= int(info.get("total_page") or 0):
            break
        time.sleep(.2)
    else:
        raise ValueError("粉丝勋章列表分页未完成")

    cards = []
    for anchor, item in found.items():
        medal = item.get("medal") or {}
        card = {"anchor": anchor, "name": (item.get("anchor_info") or {}).get("nick_name") or f"主播 {anchor}",
                "medal": medal.get("medal_name") or "", "level": int(medal.get("level") or 0),
                "live": int((item.get("room_info") or {}).get("living_status") or 0) == 1,
                "tasks": [], "error": None}
        try:
            data = client.get("/xlive/app-ucenter/v1/fansMedal/GetActivatedMedalInfo",
                              {"target_id": anchor, "csrf": client.csrf, "web_location": "444.260"}, base=LIVE)
            card["level"] = int(data.get("level") or card["level"])
            card["lighted"] = bool(data.get("is_lighted"))
            card["savings_full"] = bool(data.get("reach_free_intimacy_limit"))
            for task in data.get("task_info") or []:
                match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", task.get("sub_title") or "")
                percent = min(100, float(match[1]) / float(match[2]) * 100) if match and float(match[2]) > 0 else None
                card["tasks"].append({"name": task.get("title") or task.get("jump_type") or "任务",
                                      "progress": task.get("sub_title") or "",
                                      "done": bool(task.get("is_done")),
                                      "percent": 100 if task.get("is_done") else percent})
        except Exception:
            card["error"] = "任务进度暂未加载，请刷新"
        cards.append(card)
        time.sleep(.15)
    return sorted(cards, key=lambda x: (-x["level"], x["name"]))
