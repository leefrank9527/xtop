import argparse
import asyncio

from monitor.aio_watch_screen import aio_print_screen


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
