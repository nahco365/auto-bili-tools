"""Device cookie enrollment compatible with the .NET Gaia flow."""

import json
import logging
import random
import secrets
import time
from pathlib import Path
from urllib.request import Request

from bili_qinglong import ApiError, setting


LOG = logging.getLogger("bili")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
SCREENS = [(1920, 1080, 1048), (1600, 900, 868), (1536, 864, 832),
           (1440, 900, 868), (2560, 1440, 1408)]


def device_uuid():
    value = secrets.token_hex(18).upper()
    return f"{value[:9]}-{value[9:13]}-{value[13:18]}-{value[18:22]}-{value[22:34]}{random.randint(100000, 999999)}infoc"


def gaia_payload(uuid):
    path = Path(__file__).with_name("gaia_template.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update({"5062": str(int(time.time() * 1000)),
                 "03bf": "https%3A%2F%2Fwww.bilibili.com%2F",
                 "39c8": "333.1007.fp.risk", "df35": uuid})
    width, height, available = random.choice(SCREENS)
    fp = data["3c43"]
    fp["748e"] = [width, height]
    fp["d61f"] = [width, available]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    for key in ("13ab", "bfe9"):
        value = list(fp[key])
        for i in range(max(0, len(value) - 16), len(value)):
            if value[i] != "=":
                value[i] = random.choice(alphabet)
        fp[key] = "".join(value)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def ensure_device(client):
    if client.fields.get("buvid3"):
        return False
    response = client.get("/x/frontend/finger/spi")
    if not response.get("b_3"):
        LOG.warning("无法获取 buvid3，跳过设备建档")
        return False
    client.fields["buvid3"] = response["b_3"]
    if response.get("b_4"):
        client.fields["buvid4"] = response["b_4"]
    uuid = client.fields.get("_uuid") or device_uuid()
    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/",
               "Origin": "https://www.bilibili.com", "Content-Type": "application/json",
               "Cookie": "; ".join(f"{key}={client.fields[key]}" for key in ("buvid3", "buvid4", "b_nut") if client.fields.get(key)) + f"; _uuid={uuid}"}
    body = json.dumps({"payload": gaia_payload(uuid)}, separators=(",", ":")).encode()
    request = Request("https://api.bilibili.com/x/internal/gaia-gateway/ExClimbWuzhi",
                      data=body, method="POST", headers=headers)
    try:
        with client.opener.open(request, timeout=20) as response:
            result = json.load(response)
    except Exception as exc:
        raise ApiError(f"设备指纹上报失败：{exc}") from exc
    if result.get("code") != 0:
        raise ApiError(result.get("message") or "设备指纹上报失败", result.get("code"))
    client.fields["_uuid"] = uuid
    client.cookie = "; ".join(f"{key}={value}" for key, value in client.fields.items())
    LOG.info("设备指纹建档成功")
    return True
