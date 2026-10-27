"""Python replacement for the legacy kubectl-bilipro deployment helper."""

import argparse
import subprocess
from pathlib import Path


MANIFEST = Path(__file__).with_name("k8s.yaml")


def render(image):
    if not image or any(char.isspace() for char in image):
        raise ValueError("镜像名称不能为空或包含空白字符")
    return MANIFEST.read_text(encoding="utf-8").replace("bilitool-python:local", image)


def main(argv=None):
    parser = argparse.ArgumentParser(description="BiliBiliToolPro Python Kubernetes 管理")
    parser.add_argument("--namespace", default="bilipro")
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("init", help="创建或更新部署")
    deploy.add_argument("--image", required=True)
    deploy.add_argument("--output", action="store_true", help="仅输出清单")
    commands.add_parser("get", help="查看部署")
    delete = commands.add_parser("delete", help="删除服务与部署")
    delete.add_argument("--with-data", action="store_true", help="同时删除持久卷声明")
    commands.add_parser("version", help="显示工具版本")
    args = parser.parse_args(argv)
    if args.command == "version":
        print("BiliBiliToolPro Python kubectl helper 1.0")
        return 0
    if args.command == "init":
        manifest = render(args.image)
        if args.output:
            print(manifest)
            return 0
        return subprocess.run(["kubectl", "apply", "-n", args.namespace, "-f", "-"],
                              input=manifest, text=True, check=False).returncode
    if args.command == "get":
        return subprocess.run(["kubectl", "get", "-n", args.namespace,
                               "deployment/bilitool-python", "service/bilitool-python",
                               "pvc/bilitool-python-data"], check=False).returncode
    names = ["deployment/bilitool-python", "service/bilitool-python"]
    if args.with_data:
        names.append("pvc/bilitool-python-data")
    return subprocess.run(["kubectl", "delete", "-n", args.namespace, *names], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
