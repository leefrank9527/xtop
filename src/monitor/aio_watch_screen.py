import asyncio
import math

import aiohttp
import sys
import tty
import termios
import select
from datetime import datetime

import plotext as plt
import platform
from rich.console import Group
from rich.live import Live
from rich.text import Text
from rich.table import Table
from rich import box
from rich.align import Align
from rich.rule import Rule

from monitor.aio_docker_stats import AioDockerStats
from monitor.aio_fps_monitor import AioFpsMonitor
from monitor.aio_system_usage import AioSystemUsage
from monitor import TICKS_COLOR, TITLE_STYLE, create_basic_table, BORDER_STYLE


async def get_cpu_model_linux():
    with open("/proc/cpuinfo") as f:
        for line in f:
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


async def input_listener(stop_event):
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while not stop_event.is_set():
            # Use select with a short timeout to keep the loop responsive
            dr, _, _ = select.select([sys.stdin], [], [], 0.1)
            if dr:
                key = sys.stdin.read(1)
                if key.lower() == 'q':
                    stop_event.set()
                    break
            await asyncio.sleep(0.1)  # Yield to other tasks
    except Exception as e:
        print(f"Input error: {e}")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


async def aio_print_screen(args):
    server_url = args.server_url
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{server_url}/api/version") as resp:
            server_version = await resp.json()

    cpu_model = await  get_cpu_model_linux()

    # Create a stop event
    stop_event = asyncio.Event()

    # Start the keyboard listener as a background task
    input_task = asyncio.create_task(input_listener(stop_event))

    monitors = []
    fps_monitor = AioFpsMonitor(server_url=args.server_url)
    monitors.append(fps_monitor)

    docker_monitor = AioDockerStats()
    monitors.append(docker_monitor)

    system_monitor = AioSystemUsage()
    monitors.append(system_monitor)

    # Start the monitors
    for m in monitors:
        await m.start()

    # Helper function to create the header
    async def render_top_header():
        # 1. Get current time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Create a grid (a table without borders)
        grid = Table.grid(expand=True)

        # 3. Add two columns: Left (Title) and Right (Clock)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right", ratio=1)

        # 4. Add the content
        grid.add_row(
            Text("xtop: press 'ctrl + c' to quit", style="bold green"),
            Text(current_time, style="bold cyan"),
            Text(f"BrainFrame OS: {server_version} | CPU: {cpu_model}", style="bold green"),
        )
        # return Panel(grid, box=box.MINIMAL)
        return grid

    async def render_basic_resources_stats():
        t = create_basic_table("Resources")
        t.add_column("Metrics", justify="left", ratio=3)
        t.add_column("CPU", justify="right", ratio=1)
        t.add_column("Mem", justify="right", ratio=2)
        t.add_column("Network I/O(S)", justify="right", ratio=3)
        t.add_column("Disk", justify="right", ratio=2)

        await  system_monitor.render_basic_stats_row(t)
        await  docker_monitor.render_basic_stats_row_core(t)
        await  docker_monitor.render_basic_stats_row_all(t)

        return t

    async def make_chart(width):
        plt.clf()  # Clear previous frame
        plt.clear_color()
        plt.ticks_color(TICKS_COLOR)
        # plt.axes_color("black")

        calc_width = width - 3 if width > 80 else 77
        plt.plot_size(calc_width, 25)
        plt.limit_size(False, False)

        # --- RIGHT AXIS: Percentages ---
        # CPU and Memory moved to the right side
        plt.plot(system_monitor.cpu_history, label="CPU %", color="cyan", marker="braille", yside="right")
        plt.plot(system_monitor.mem_history, label="Mem %", color="magenta", marker="braille", yside="right")

        # --- LEFT AXIS: FPS ---
        # Primary focus is now FPS on the left
        plt.plot(fps_monitor.tot_stat.fps_history, label="FPS", color="red", marker="braille", yside="left")
        max_fps = max(fps_monitor.tot_stat.fps_history)
        max_fps = math.floor(max_fps) + 1 if max_fps > 0 else 20

        # --- Configuration ---
        # plt.title(f"{WHITE}FPS (Left) vs System Usage (Right){RESET}")

        plt.grid(False, False)

        # Configure LEFT Y-Axis (FPS)
        plt.ylabel("FPS", yside="left")
        plt.ylim(0, max_fps, yside="left")  # FPS Scale

        # Configure RIGHT Y-Axis (Percentage)
        plt.ylabel("Usage (%)", yside="right")
        plt.ylim(0, 100, yside="right")  # Percentage Scale

        return plt.build()

    try:
        with Live(Group(), refresh_per_second=1, screen=True) as live:
            while not stop_event.is_set():
                current_width = live.console.width

                # left_group = await  get_stat_table_group()
                try:
                    basic_fps_table = await fps_monitor.render_basic_stats()
                    basic_resources_table = await  render_basic_resources_stats()

                except Exception as e:
                    print(e)

                left_group = Group(
                    basic_resources_table,
                    Align.left("FPS (Left) vs System Resource (Right)", style=TITLE_STYLE),
                    Text.from_ansi(await make_chart(current_width * 0.7)),
                    Rule(characters=" "),
                    await docker_monitor.render_stats_table(),
                )

                right_group = Group(
                    basic_fps_table,
                    Rule(characters=" "),
                    await fps_monitor.render_detailed_streams_status(),
                )

                layout_table = Table(show_header=False, show_lines=False, box=box.ROUNDED, expand=True, border_style=BORDER_STYLE)
                layout_table.add_column("left", justify="left", ratio=7)
                layout_table.add_column("right", justify="right", ratio=3)

                layout_table.add_row(left_group, right_group)

                root_group = Group(
                    await render_top_header(),
                    layout_table,
                )

                live.update(root_group)

                await asyncio.sleep(delay=1.0)
    finally:
        input_task.cancel()
        for m in monitors:
            await m.close()
