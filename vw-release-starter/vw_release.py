#!/usr/bin/env python3
"""第一步：只读检查本机 Vaultwarden；不实现备份、部署或恢复。"""

import argparse
import datetime
import json
import re
import socket
import subprocess

# 固定 ECS 本机的 rootful Docker，避免意外读取另一个 Docker context。
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
CONTAINERS = {"production": "vaultwarden", "candidate": "vaultwarden-candidate"}
# 在 Docker 输出端选择字段，不输出完整 Config、环境变量或健康检查日志。
INSPECT_FORMAT = """{
  "image_ref": {{json .Config.Image}},
  "image_id": {{json .Image}},
  "state": {{json .State.Status}},
  "health": {{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},
  "mounts": {{json .Mounts}},
  "ports_configured": {{json .HostConfig.PortBindings}}
}"""


def docker_read(*args):
    try:
        result = subprocess.run(
            DOCKER + list(args), capture_output=True, text=True, timeout=15
        )
    except FileNotFoundError:
        raise RuntimeError("未找到 docker 命令；请在安装了 Docker 的 ECS 本机运行。") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker 读取超过 15 秒；本次状态未知。") from None
    except OSError:
        raise RuntimeError("无法执行 Docker 读取；本次状态未知。") from None
    if result.returncode:
        # 不转发原始 stderr，它可能包含运行环境中的敏感信息。
        raise RuntimeError(
            "Docker 读取失败；请在 ECS 本机检查 Docker 服务、socket 和读取权限。"
        )
    return result.stdout


def collect_status():
    # 只有成功列出容器后才能判断缺失，权限/连接失败不能当作不存在。
    names = set(docker_read("container", "ls", "--all", "--format", "{{.Names}}").splitlines())
    report = {
        "read_ok": CONTAINERS["production"] in names,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "docker_endpoint": DOCKER[2],
        "mode": "read_only",
        "compatibility": "NOT_TESTED",
    }
    for role, name in CONTAINERS.items():
        item = {"name": name, "exists": name in names}
        if item["exists"]:
            info = json.loads(docker_read("container", "inspect", "--format", INSPECT_FORMAT, name))
            if not isinstance(info, dict) or not isinstance(info["image_ref"], str):
                raise ValueError("Invalid Docker response")
            item.update({
                "image_ref": info["image_ref"],
                "image_id": info["image_id"],
                "image_reference_uses_digest": bool(
                    re.fullmatch(r".+@sha256:[0-9a-f]{64}", info["image_ref"])
                ),
                "state": info["state"],
                "health": info["health"],
                "data_mounts": [
                    {"type": m["Type"], "source": m["Source"],
                     "destination": m["Destination"], "writable": m["RW"]}
                    for m in (info["mounts"] or []) if m["Destination"] == "/data"
                ],
                "ports_configured": info["ports_configured"],
            })
        report[role] = item
    if not report["read_ok"]:
        report["error"] = "未找到名为 vaultwarden 的生产容器；请核对容器名。"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="vw-release", description=__doc__)
    parser.add_argument("command", choices=["status"], help="只读采集，不判断兼容性")
    parser.parse_args(argv)
    try:
        report = collect_status()
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "Docker 返回的数据不完整；本次状态未知。"
        report = {"read_ok": False, "compatibility": "NOT_TESTED", "error": message}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["read_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
