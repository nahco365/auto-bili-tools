# BiliBiliToolPro 青龙 Python 版

此目录把原项目的 **Console 自动任务**移植为 Python 3.9+ 脚本，适配青龙环境变量和定时任务。使用 Python 标准库，无需安装依赖。完整 Web 版位于同一发布目录的 [`webui`](../webui/README.md)。请将以下文件放在青龙同一个脚本目录：

- `bili_qinglong.py`：入口、每日任务、直播签到、漫画、积分、抽奖、充电、取关。
- `bili_medal.py`：粉丝勋章互动和观看心跳。
- `bili_login.py`、`qrcodegen.py`：终端字符二维码、扫码登录及青龙 OpenAPI Cookie 保存。二维码编码器来自 Project Nayuki，按其文件头的 MIT 许可证分发。
- `bili_device.py`、`gaia_template.json`：设备指纹建档。

## 环境变量

在青龙环境变量中添加 `BiliBiliCookies__1`，值为完整 B 站 Cookie，至少包含 `SESSDATA`、`bili_jct`、`DedeUserID`。第二个账号为 `BiliBiliCookies__2`，以此类推。Cookie 变量只读取不带 `Ray_` 前缀的名称；其他任务设置仍使用 `Ray_` 前缀。

扫码登录：青龙环境变量中配置 `Ray_QingLongConfig__ClientId` 和 `Ray_QingLongConfig__ClientSecret` 后，手动运行 `python3 bili_qinglong.py Login`；独立发布包也提供 `bili_task_login.py`。日志会显示可直接在深色 Shell 扫描的字符二维码、二维码链接，以及参数提示；浅色终端可设置 `Ray_LoginConfig__QrLightBackground=true` 调整字符颜色。扫码后按 UID 自动更新已有 `BiliBiliCookies__N`，或新建一个编号。OpenAPI 默认连接青龙容器内的 `http://127.0.0.1:5700`；若面板地址不同，设置 `Ray_QingLongConfig__Url`。**无论是否具备自动写入条件，也无论写入是否成功，扫码后都会在日志中输出完整 Cookie 和写入结果**，便于手动补救；请限制该日志访问权限。

## 任务调度

在青龙中分别创建定时任务，命令写为 `python3 bili_qinglong.py 任务名`。以下时间参照原项目的配置或青龙脚本，可按需修改：

| 任务名 | 功能 | 示例 cron |
| --- | --- | --- |
| `Daily` | 每日登录、观看、分享、专栏或视频投币、年度大会员权益 | `0 9 * * *` |
| `Manga` | 漫画签到与阅读 | `0 14 * * *` |
| `MangaPrivilege` | 漫画会员权益 | `0 15 * * *` |
| `Silver2Coin` | 银瓜子兑换硬币 | `0 8 * * *` |
| `Charge` | 使用 B 币券充电 | `0 12 28 * *` |
| `VipPrivilege` | 年度大会员权益单独领取 | `0 1 * * *` |
| `VipBigPoint` | 大会员积分签到、任务领取和完成 | `7 1 * * *` |
| `LiveLottery` | 天选抽奖和新关注分组 | `0 22 * * *` |
| `LiveFansMedal` | 粉丝勋章弹幕、点赞、观看 | `5 0 * * *` |
| `UnfollowBatched` | 按分组批量取关 | `0 6 1 * *` |
| `Login` | 扫码登录 | 手动运行 |
| `LiveSign` | 直播签到 | `0 9 * * *` |
| `Test` | 测试 Cookie | 手动运行 |
| `CookieTest` | 独立的 Cookie 检测入口 | 手动运行 |

支持一次执行多个任务，例如 `python3 bili_qinglong.py Daily Manga`，或设置 `Ray_RunTasks=Daily&Manga`。不指定时默认运行 `Daily&LiveSign&Manga&MangaPrivilege&Silver2Coin`。`Daily` 已包含 `VipPrivilege`，一般不需要在同一次执行中重复运行。

## 原配置兼容

与原项目相同，配置可用 `Ray_配置节__属性名` 形式传入。常用示例：

```text
Ray_DailyTaskConfig__NumberOfCoins=5
Ray_DailyTaskConfig__NumberOfProtectedCoins=0
Ray_DailyTaskConfig__CoinDonationStopLevel=0
Ray_DailyTaskConfig__SupportUpIds=123456,789012
Ray_DailyTaskConfig__IsDonateCoinForArticle=false
Ray_DailyTaskConfig__SelectLike=true
Ray_LiveFansMedalTaskConfig__LikeNumber=30
Ray_LiveFansMedalTaskConfig__SendDanmakuNumber=1
Ray_LiveFansMedalTaskConfig__HeartBeatNumber=70
Ray_LiveLotteryTaskConfig__AutoGroupFollowings=true
Ray_UnfollowBatchedTaskConfig__Count=20
Ray_ChargeTaskConfig__AutoChargeUpId__123456=987654
Ray_ChargeTaskConfig__AutoChargeUpId__234567=876543
Ray_Security__IntervalSecondsBetweenRequestApi=10
```

`Ray_DeviceCookie__Buvid3`、`Ray_DeviceCookie__Buvid4`、`Ray_DeviceCookie__BNut` 可固定设备 Cookie。缺少 `buvid3` 时，程序会调用 `finger/spi` 和 Gaia 接口建档，并尝试通过青龙 OpenAPI 保存新的 Cookie。

充电目标的变量名末尾为**登录账号的 UID**，值为该账号要充电的 UP UID。上例让登录账号 `123456` 向 `987654` 充电，让账号 `234567` 向 `876543` 充电。多账号时未给某个账号设置目标，就跳过该账号；通用变量 `Ray_ChargeTaskConfig__AutoChargeUpId` 仅在只有一个账号时生效。没有任何目标时不会充电。

## 验证与范围

运行 `python3 -m unittest test_bili_qinglong.py` 可进行不联网的逻辑测试。当前测试覆盖账号选择、投币限额、任务容错、取关白名单、勋章进度与设备模板。**尚未使用真实账号对所有 B 站接口做端到端验证**；首次执行请查看青龙日志，尤其是大会员积分和直播心跳。完整 Python 版另提供 Web 管理、持久调度、自动补做和多渠道通知；青龙面板自身的通知配置也可继续使用。
