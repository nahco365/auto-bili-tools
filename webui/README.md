# WebUI 版

包含 Web 页面、多账号管理、扫码登录、SQLite、定时调度、执行记录与通知。Python 3.9+，运行时不需要 .NET。

## Python 启动

在本目录执行：

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

在本目录创建本地 `.env` 文件，写入 `BILI_ADMIN_PASSWORD=你的强密码`，然后执行：

```sh
docker compose up -d --build
```

Compose 默认只监听本机 `127.0.0.1:8080`，持久数据保存在本目录的 `data/`。若要远程访问，请使用 HTTPS 反向代理，并设置 `BILI_HTTPS=true`。不要把 `.env` 或 `data/` 提交到仓库。

## 任务与验证

WebUI 中可添加账号、设置任务计划，并按登录账号 UID 分别填写充电目标；未填写的账号不会充电。首次部署建议先运行 Cookie 检测，再按需启用计划。青龙和 WebUI 使用同一账号时，只在一处启用同一任务的计划。

离线验证：`python -m unittest test_python_port.py test_bili_qinglong.py -q`。任务仍依赖 B 站实时接口，线上结果请查看执行日志。

源码依据原 BiliBiliToolPro 重写，遵循本目录的 [LICENSE](LICENSE)。`qrcodegen.py` 的 MIT 许可见其文件头。
