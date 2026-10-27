# 青龙订阅拉取

本仓库同时含有 WebUI 源码。订阅时只选择 `qinglong/` 下的任务入口和运行依赖，避免把 `webui/` 的 Python 文件识别为青龙任务。青龙容器需要能访问 GitHub，并提供 Python 3.9+。

## 在青龙面板创建订阅

进入「订阅管理 → 新建订阅」，按下表填写。不同青龙版本的界面名称可能略有差异。

| 字段 | 值 |
| --- | --- |
| 名称 | `auto-bili-tools` |
| 类型 | 公开仓库；若仓库设为私有，选择私有仓库并在面板中配置访问凭据 |
| 链接 | `https://github.com/nahco365/auto-bili-tools.git` |
| 分支 | `main` |
| 定时类型 / 定时规则 | `crontab` / `0 3 * * *`，这是**拉取更新**的时间，不是 B 站任务时间 |
| 白名单 | `^qinglong/bili_task_.*\.py$` |
| 黑名单 | 留空 |
| 依赖文件 | `^qinglong/(bili_qinglong|bili_medal|bili_login|bili_device|qrcodegen)\.py$|^qinglong/gaia_template\.json$` |
| 文件后缀 | `py json` |
| 自动添加任务 / 自动删除任务 | 均关闭，先手动检查并创建所需任务 |

保存后**手动运行一次订阅**，查看订阅日志，并在「脚本管理」确认 `qinglong/` 目录中有 `bili_task_cookie_test.py`、`bili_qinglong.py`、`bili_login.py`、`bili_device.py`、`bili_medal.py`、`qrcodegen.py` 和 `gaia_template.json`。其中 `gaia_template.json` 依赖 `json` 后缀设置；缺少任一运行依赖时不要运行任务。

## 配置账号并建立任务

在「环境变量」新增 `BiliBiliCookies__1`，值为完整 Cookie；多个账号依次使用 `BiliBiliCookies__2`、`BiliBiliCookies__3`。旧的 `Ray_BiliBiliCookies__N` **不会读取**。也可先运行登录入口扫码，按 [青龙版说明](README.md) 配置 OpenAPI 后自动保存 Cookie。

在「定时任务」中手动添加需要的入口。仓库订阅目录名以「脚本管理」实际显示为准；当前青龙通常会将此仓库 `main` 分支放在 `nahco365_auto-bili-tools_main` 下：

```text
task nahco365_auto-bili-tools_main/qinglong/bili_task_cookie_test.py
task nahco365_auto-bili-tools_main/qinglong/bili_task_daily.py
task nahco365_auto-bili-tools_main/qinglong/bili_task_vip_big_point.py
task nahco365_auto-bili-tools_main/qinglong/bili_task_charge.py
task nahco365_auto-bili-tools_main/qinglong/bili_task_login.py
```

先手动运行 `cookie_test` 检查 Cookie。`login` 和 `cookie_test` 只需手动运行。`daily`、`vip_big_point`、`charge` 的示例 cron 见 [完整任务说明](PYTHON_QINGLONG.md)；确认日志正常后再启用相应计划。充电目标按登录账号 UID 设置 `Ray_ChargeTaskConfig__AutoChargeUpId__登录UID=目标UPUID`，未配置目标的账号会跳过充电。

若订阅成功却提示 `ModuleNotFoundError`，先核对订阅的「依赖文件」与「文件后缀」；若找不到 `gaia_template.json`，确认后缀含 `json`。任务路径不对时，以脚本管理中实际目录替换上面的 `nahco365_auto-bili-tools_main`。订阅更新只同步脚本，Cookie 等环境变量仍留在青龙面板中。不要把 Cookie、OpenAPI 密钥写入仓库或任务命令。
