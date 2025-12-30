import argparse
import asyncio
import subprocess

from monitor.aio_watch_screen import aio_print_screen


def get_version():
    try:
        from importlib.metadata import version
        __version__ = version("xtop-cli")
    except Exception:
        __version__ = "0.0.0"

    return __version__


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="xtop")

    # Universal arguments
    parser.add_argument(
        "--server-url",
        default="http://172.17.0.1",
        help="The address of the server",
    )

    return parser.parse_args()


async def _main():
    args = _parse_args()
    # print(args)

    screen = asyncio.create_task(aio_print_screen(args=args))
    await asyncio.gather(screen, return_exceptions=True)


def main():
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


def run_docker():
    args = _parse_args()
    docker_name = "xtop"
    server_url = args.server_url
    docker_image_name = "leefrank9527/xtop-docker"

    run_cmd = [
        "docker", "run", "-it", "--restart", "unless-stopped",
        "--name", docker_name,
        "--privileged",
        "-e", f"SERVER_URL={server_url}",
        "-v", "/dev/bus/usb:/dev/bus/usb",
        "-v", "/dev/dri:/dev/dri",
        "-v", "/etc/localtime:/etc/localtime",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        f"{docker_image_name}:{get_version()}",
    ]

    stop_cmd = ["docker", "stop", docker_name]
    rm_cmd = ["docker", "rm", docker_name]

    try:
        subprocess.run(run_cmd, check=True)
    finally:
        subprocess.run(stop_cmd, check=False)
        subprocess.run(rm_cmd, check=False)
