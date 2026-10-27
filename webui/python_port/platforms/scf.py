"""Tencent SCF Python handler; configure BiliBiliCookies__N as environment variables."""

import logging
import os

from bili_qinglong import TASKS, main


def main_handler(event, context):
    requested = event.get("task") or os.getenv("BILI_SCF_TASK", "Daily")
    tasks = requested.replace(",", "&").split("&") if isinstance(requested, str) else requested
    tasks = [task.strip() for task in tasks if isinstance(task, str) and task.strip()]
    if not tasks or any(task not in TASKS for task in tasks):
        raise ValueError("task 必须是受支持的任务名")
    logging.basicConfig(level=logging.INFO)
    return {"tasks": tasks, "exit_code": main(tasks)}
