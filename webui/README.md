# WebUI 版

包含 Web 页面、多账号管理、扫码登录、SQLite、定时调度、执行记录与通知。Python 3.9+，运行时不需要 .NET。

从 GitHub 克隆整个仓库后，先进入 `webui/` 再运行下面的命令：

```sh
git clone https://github.com/nahco365/auto-bili-tools.git
cd auto-bili-tools/webui
```

公开仓库可直接克隆；私有仓库需先配置 GitHub 访问权限。直接下载 ZIP 后，也要进入其中的 `webui/` 目录。

## Python 启动

在 `webui/` 目录执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r python_port/requirements.txt
export BILI_ADMIN_PASSWORD='请换成自己的强密码'
python -m python_port.server
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python_port\requirements.txt
$env:BILI_ADMIN_PASSWORD = '请换成自己的强密码'
.\.venv\Scripts\python.exe -m python_port.server
```

打开 `http://127.0.0.1:8080`，用户名为 `admin`。`BILI_ADMIN_PASSWORD` 仅在新数据库首次初始化时生效；已有数据库请在 Web 管理页面修改密码。默认数据库路径为 `data/bilitool.sqlite`，可用 `BILI_PY_DB` 更改。请备份数据库和同目录下的 `.secret` 文件，并避免提交到 GitHub。

## Docker Compose

在 `webui/` 目录创建本地 `.env` 文件，写入 `BILI_ADMIN_PASSWORD=你的强密码`，然后在同一目录执行：

```sh
docker compose up -d --build
```

Compose 默认只监听本机 `127.0.0.1:8080`，持久数据保存在本目录的 `data/`。若要远程访问，请使用 HTTPS 反向代理，并设置 `BILI_HTTPS=true`。不要把 `.env` 或 `data/` 提交到仓库。

## 部署注意事项

- `BILI_ADMIN_PASSWORD` 只在数据库第一次创建时设置管理员密码。以后改 `.env` 不会重置密码，请在 WebUI「管理员」页面修改。未设置该变量直接运行 Python 时会使用公开的默认密码，部署前应明确设置。
- 保留并备份 `webui/data/`（或 `BILI_PY_DB` 指定的位置），其中包含账号 Cookie、计划、日志和会话密钥。更新代码时不要删除这个目录；迁移服务时数据库与同名 `.secret` 文件一起迁移。
- Compose 的 `127.0.0.1:8080:8080` 仅允许本机访问。远程访问可通过 HTTPS 反向代理接入；若通过其他方式开放端口，应同时检查登录密码和网络访问控制。
- 青龙与 WebUI 可以共用账号，但同一任务的计划应只在一个平台启用，避免重复投币、领取或充电。多账号充电目标可在 WebUI 按登录 UID 分别填写；留空不会充电。
- WebUI 使用 `python_port/requirements.txt` 的依赖，青龙脚本使用标准库。不要把 WebUI 的数据库、`.env` 或管理员密码放进青龙订阅和 GitHub 仓库。

## 任务与验证

WebUI 中可添加账号、设置任务计划，并按登录账号 UID 分别填写充电目标；未填写的账号不会充电。首次部署建议先运行 Cookie 检测，再按需启用计划。青龙和 WebUI 使用同一账号时，只在一处启用同一任务的计划。

离线验证：`python -m unittest test_python_port.py test_bili_qinglong.py -q`。任务仍依赖 B 站实时接口，线上结果请查看执行日志。

源码依据原 BiliBiliToolPro 重写，遵循本目录的 [LICENSE](LICENSE)。`qrcodegen.py` 的 MIT 许可见其文件头。
