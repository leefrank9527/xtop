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
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box
from rich.align import Align

from monitor.aio_docker_stats import AioDockerStats
from monitor.aio_fps_monitor import AioFpsMonitor
from monitor.aio_system_usage import AioSystemUsage
from monitor import BORDER_STYLE, HEADER_STYLE, TICKS_COLOR, create_kv_grid


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
            brainframe_os_version = await resp.json()

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
            Text(f"BrainFrame OS: {brainframe_os_version} | CPU: {cpu_model}", style="bold green"),
            Text(current_time, style="bold cyan"),
            Text("Press 'q' to quit", style="bold red")
        )
        return grid

    async def get_stat_table_group():

        # FPS
        fps_latest = fps_monitor.get_stat_latest()

        fps_throughout_grid = await fps_monitor.get_stat_throughout_grid()
        fps_streams_grid = await fps_monitor.get_stat_streams_grid()
        cpu_count, cpu_content, mem_total_gb, mem_content, system_grid = await  system_monitor.get_stat_grid()

        core_cpu_count, core_cpu_percent, core_mem_limitation, core_mem_percent, core_mem_usage, core_net_io, docker_core_grid = await docker_monitor.basic_core_stats_grid()

        basic_rows = [
            ("Fps", fps_latest),
            (f"System CPU: {cpu_count}C", cpu_content),
            (f"System Mem: {mem_total_gb:.2f}GB", mem_content),
            (f"Core CPU: {core_cpu_count}", core_cpu_percent),
            (f"Core Mem: {core_mem_limitation}", f"{core_mem_percent} / {core_mem_usage}"),
        ]
        basic_grid = create_kv_grid("Basic Stats", basic_rows)

        group = Group(
            Align.left("Critical Stats", style="bold white"),
            basic_grid,
            fps_throughout_grid,
            fps_streams_grid,
            system_grid,
            docker_core_grid,
        )

        # master_table = Table(box=box.SQUARE, show_lines=True, expand=True,
        #                      header_style=HEADER_STYLE,
        #                      border_style=BORDER_STYLE
        #                      )
        # master_table.add_column("Metrics", justify="center", vertical="middle")
        # master_table.add_column("FPS", justify="center")
        # master_table.add_column("FPS THROUGHOUT", justify="center")
        # master_table.add_column("FPS STREAMS", justify="center")
        # master_table.add_column("System", justify="center")
        # master_table.add_column("Core Container", justify="center")
        # master_table.add_row(
        #     Align("Value", vertical="middle", align="center"),
        #     await fps_monitor.get_stat_table_latest(),
        #     await fps_monitor.get_stat_table_throughout(),
        #     await fps_monitor.get_stat_table_streams(),
        #     await system_monitor.get_stat_table(),
        #     await docker_monitor.basic_core_stats_table()
        # )
        #
        # return master_table
        return group

    async def make_chart(width):
        plt.clf()  # Clear previous frame
        plt.clear_color()
        plt.ticks_color(TICKS_COLOR)
        # plt.axes_color(BORDER_STYLE)

        calc_width = width - 3 if width > 80 else 77
        plt.plot_size(calc_width, 25)
        plt.limit_size(False, False)

        # --- RIGHT AXIS: Percentages ---
        # CPU and Memory moved to the right side
        plt.plot(system_monitor.cpu_history, label="CPU %", color="red", marker="braille", yside="right")
        plt.plot(system_monitor.mem_history, label="Mem %", color="cyan", marker="braille", yside="right")

        # --- LEFT AXIS: FPS ---
        # Primary focus is now FPS on the left
        plt.plot(fps_monitor.tot_stat.fps_history, label="FPS", color="white", marker="braille", yside="left")
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

    divider = Panel(
        Text("│"),
        border_style="black",
        style="bright_white on black",
        box=box.SQUARE,
    )

    margin = Panel(
        Text("│"),
        box=box.MINIMAL,
    )

    layout = Layout()
    layout.split_row(
        Layout(name="left", ratio=1),
        Layout(margin, size=1),
        Layout(divider, size=1),
        Layout(margin, size=1),
        Layout(name="right", ratio=4),
    )

    try:
        with Live(layout, refresh_per_second=2, screen=True) as live:
            while not stop_event.is_set():
                current_width = live.console.width

                left_group = await  get_stat_table_group()

                right_group = Group(
                    Align.left("Docker Container Stats", style="bold white"),
                    await docker_monitor.stats_table(),
                    Align.left("\r\nFPS (Left) vs System Usage (Right)", style="bold white"),
                    Text.from_ansi(await make_chart(current_width * 0.8)),
                    Align.left("\r\nStatus of streams", style="bold white"),
                    await fps_monitor.get_detailed_streams_table(),
                )

                layout["left"].update(left_group)
                layout["right"].update(right_group)

                dashboard_group = Group(
                    await render_top_header(),
                    Align.center(" "),
                    layout,
                    Align.center(" End "),
                )

                live.update(dashboard_group)
                # live.update(layout)

                await asyncio.sleep(delay=1.0)
    finally:
        input_task.cancel()
        for m in monitors:
            await m.close()
