# 青龙版

Python 3.9+，无需安装第三方依赖。推荐按 [订阅拉取说明](SUBSCRIPTION.md) 从 GitHub 同步；也可将本目录文件上传到青龙的同一个脚本目录，例如 `bilitool_python_port/`。不要上传账号 Cookie 或本地数据库。

## 快速开始

1. 在青龙的「环境变量」中新增 `BiliBiliCookies__1`，值为完整 Cookie；或先创建扫码登录任务，运行后按日志提示扫码。登录所需的字符二维码会直接显示在任务日志中。
2. 创建手动任务 `task bilitool_python_port/bili_task_cookie_test.py`，运行并确认账号有效。若文件放在脚本根目录，去掉命令中的 `bilitool_python_port/`。
3. 按需创建每日任务 `task bilitool_python_port/bili_task_daily.py`、大会员积分任务 `task bilitool_python_port/bili_task_vip_big_point.py` 和充电任务 `task bilitool_python_port/bili_task_charge.py`。包内的 `bili_task_*.py` 是各任务的独立入口。

扫码登录任务为 `task bilitool_python_port/bili_task_login.py`。需要自动把扫码得到的 Cookie 写回青龙时，设置 `Ray_QingLongConfig__ClientId`、`Ray_QingLongConfig__ClientSecret`，面板不在容器本机时再设置 `Ray_QingLongConfig__Url`。无论写回是否成功，完整 Cookie 都会输出到登录任务日志，请控制日志访问权限。

多账号充电目标按登录账号 UID 设置，例如 `Ray_ChargeTaskConfig__AutoChargeUpId__123456=987654`。未设置目标的账号跳过充电。只有一个账号时也兼容通用变量 `Ray_ChargeTaskConfig__AutoChargeUpId`。

任务说明、环境变量和计划示例见 [PYTHON_QINGLONG.md](PYTHON_QINGLONG.md)。离线验证：`python3 -m unittest test_bili_qinglong.py -q`。

源码依据原 BiliBiliToolPro 重写，遵循本目录的 [LICENSE](LICENSE)。`qrcodegen.py` 的 MIT 许可见其文件头。
