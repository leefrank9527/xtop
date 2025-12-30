#!/usr/bin/env -S .venv/bin/python3
import argparse
import subprocess
import sys
import os

try:
    from importlib.metadata import version

    __version__ = version("xtop-cli")
except Exception:
    __version__ = "0.0.0"

VERSION = __version__
SERVER_URL = "http://172.17.0.1"

DOCKER_NAME = "xtop"
DOCKER_IMAGE_NAME = "leefrank9527/xtop-docker"


def run(cmd: list[str], check: bool = True):
    """Run a shell command and stream output."""
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=check)


def debug():
    venv_activate = ".venv/bin/activate"
    if not os.path.exists(venv_activate):
        print("❌ .venv not found")
        sys.exit(1)

    run(["python3", "src/main.py"])


def build():
    run([
        "docker", "build",
        "-f", "Dockerfile",
        "--tag", f"{DOCKER_IMAGE_NAME}:{VERSION}",
        "."
    ])
    run([
        "docker", "tag",
        f"{DOCKER_IMAGE_NAME}:{VERSION}",
        f"{DOCKER_IMAGE_NAME}:latest"
    ])


def up():
    run([
        "docker", "run", "-it",
        "--restart", "unless-stopped",
        "--name", DOCKER_NAME,
        "--privileged",
        "-e", f"SERVER_URL={SERVER_URL}",
        "-v", "/dev/bus/usb:/dev/bus/usb",
        "-v", "/dev/dri:/dev/dri",
        "-v", "/etc/localtime:/etc/localtime",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        f"{DOCKER_IMAGE_NAME}:latest"
    ])

    # same behavior as bash script
    run(["docker", "stop", DOCKER_NAME], check=False)
    run(["docker", "rm", DOCKER_NAME], check=False)


def down():
    run(["docker", "stop", DOCKER_NAME], check=False)
    run(["docker", "rm", DOCKER_NAME], check=False)


def logs():
    run(["docker", "logs", "-f", DOCKER_NAME])


def exec_shell():
    run(["docker", "exec", "-it", DOCKER_NAME, "bash"])


def push():
    run(["docker", "push", f"{DOCKER_IMAGE_NAME}:{VERSION}"])
    run(["docker", "push", f"{DOCKER_IMAGE_NAME}:latest"])


def main():
    parser = argparse.ArgumentParser(
        prog="xtop",
        description="xtop: Monitor for FPS, System Usage and Docker Stats"
    )

    parser.add_argument(
        "command",
        choices=["debug", "build", "up", "down", "logs", "exec", "push"],
        help="command to run"
    )

    args = parser.parse_args()

    commands = {
        "debug": debug,
        "build": build,
        "up": up,
        "down": down,
        "logs": logs,
        "exec": exec_shell,
        "push": push,
    }

    commands[args.command]()


if __name__ == "__main__":
    main()
