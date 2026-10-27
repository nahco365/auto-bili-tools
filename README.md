# BiliBiliToolPro Python

基于原 [BiliBiliToolPro](https://github.com/RayWangQvQ/BiliBiliToolPro) 的 Python 重写版。项目按部署方式分成两个独立目录，运行时不依赖 .NET：

| 目录 | 用途 | 依赖 |
| --- | --- | --- |
| [qinglong](qinglong/README.md) | 青龙脚本、终端扫码登录、Cookie 检测、定时任务 | Python 3.9+ 标准库 |
| [webui](webui/README.md) | Web 管理、多账号、SQLite、调度与执行日志 | Python 3.9+、`webui/python_port/requirements.txt` |

两个目录可分别复制或发布。运行同一账号的定时任务时，请在青龙和 WebUI 中只启用一处计划，避免重复执行。默认不配置充电目标时不会充电。

## 发布前

此目录由工作区的 `python build_github_release.py` 生成，仅复制明确列出的源码、模板、测试与文档。`data/`、Cookie、数据库、会话密钥、OpenAPI 凭据和本地环境文件不应提交。根目录的 `.gitignore` 也会拦截这些常见文件。

本项目是基于 GPL-3.0 项目的重写，见 [LICENSE](LICENSE)。`qrcodegen.py` 来自 Project Nayuki，以其文件头的 MIT 许可证发布。B 站接口可能变化，首次运行任务请检查日志。
