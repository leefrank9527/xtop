import asyncio
import time
from collections import deque

import psutil

from rich import box
from rich.table import Table

from monitor import BORDER_STYLE, HEADER_STYLE, HISTORY_SIZE


class AioSystemUsage:
    def __init__(self, history_size=HISTORY_SIZE):
        self.history_size = history_size

        # History Deques
        self.cpu_history = deque([0.0] * history_size, maxlen=history_size)
        self.mem_history = deque([0.0] * history_size, maxlen=history_size)  # Added back

        # State Variables
        self.cpu_pct = 0
        self.mem_info = None
        self.disk_info = None
        self.cpu_count = psutil.cpu_count(logical=True)
        self.load_avg = (0, 0, 0)

        # Network rate calculation vars
        self.net_sent_speed = 0
        self.net_recv_speed = 0
        self.last_net_io = psutil.net_io_counters()
        self.last_time = time.time()

        self.task_event_loop = None

    async def start(self):
        self.task_event_loop = asyncio.create_task(self._event_loop())

    async def close(self):
        if self.task_event_loop:
            self.task_event_loop.cancel()

    async def _event_loop(self):
        while True:
            current_time = time.time()

            # 1. CPU
            self.cpu_pct = psutil.cpu_percent(interval=None)
            self.cpu_history.append(self.cpu_pct)

            if hasattr(psutil, "getloadavg"):
                self.load_avg = psutil.getloadavg()

            # 2. Memory
            self.mem_info = psutil.virtual_memory()
            self.mem_history.append(self.mem_info.percent)  # Append % to history

            # 3. Disk
            self.disk_info = psutil.disk_usage('/')

            # 4. Network
            net_io = psutil.net_io_counters()
            time_delta = current_time - self.last_time

            if time_delta > 0.0:
                self.net_sent_speed = (net_io.bytes_sent - self.last_net_io.bytes_sent) / time_delta
                self.net_recv_speed = (net_io.bytes_recv - self.last_net_io.bytes_recv) / time_delta

            self.last_net_io = net_io
            self.last_time = current_time

            sleep_time = max(0.1, 1 - time_delta)
            await asyncio.sleep(delay=sleep_time)

    def _bytes_to_gb(self, bytes_val):
        if bytes_val is None: return 0.0
        return bytes_val / (1024 ** 3)

    def _format_net_speed(self, bytes_per_sec):
        if bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec / 1024:.1f}KB/s"
        return f"{bytes_per_sec / (1024 * 1024):.1f}MB/s"

    def get_cpu_stat(self):
        # Create a list copy to avoid modification during iteration issues
        data = list(self.cpu_history)
        if not data: return 0, 0, 0
        return min(data), max(data), sum(data) / len(data)

    def get_mem_stat(self):
        # Create a list copy to avoid modification during iteration issues
        data = list(self.mem_history)
        if not data: return 0, 0, 0
        return min(data), max(data), sum(data) / len(data)

    async def get_stat_table(self):
        # CPU Stats
        cpu_min, cpu_max, cpu_avg = self.get_cpu_stat()
        load_1, load_5, load_15 = self.load_avg

        # Memory Stats
        mem_min, mem_max, mem_avg = self.get_mem_stat()  # Get history stats
        mem_used_gb = self._bytes_to_gb(self.mem_info.used if self.mem_info else 0)
        mem_total_gb = self._bytes_to_gb(self.mem_info.total if self.mem_info else 0)

        # Disk Stats
        disk_used_gb = self._bytes_to_gb(self.disk_info.used if self.disk_info else 0)
        disk_total_gb = self._bytes_to_gb(self.disk_info.total if self.disk_info else 0)
        disk_pct = self.disk_info.percent if self.disk_info else 0

        # Network Stats
        net_sent = self._format_net_speed(self.net_sent_speed)
        net_recv = self._format_net_speed(self.net_recv_speed)

        # Create Table
        table = Table(
            # box=box.ROUNDED,
            box=box.SIMPLE_HEAD,
            show_edge=False,
            padding=(0, 1),
            expand=True,
            collapse_padding=True, show_lines=True,
            title=None,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        table.add_column(f"CPU: {self.cpu_count}C", justify="left", style="white")
        table.add_column(f"Mem: {mem_total_gb:.2f}GB", justify="left", style="white")
        table.add_column(f"Disk: {disk_total_gb:.2f}GB", justify="left", style="white")
        table.add_column("Network(UP/Down)", justify="left", style="white")

        # CPU Content
        # cpu_content = f"{self.cpu_pct:.2f}%/{load_1:.2f}, {load_5:.2f}, {load_15:.2f}"
        cpu_content = f"{self.cpu_pct * self.cpu_count:.2f}%"

        # Memory Content (GB + History Stats)
        mem_percent = 0 if self.mem_info is None else self.mem_info.percent
        mem_content = f"{mem_used_gb:.2f}GB/{mem_percent:.2f}%"

        disk_content = f"{disk_pct:.2f}%/{disk_used_gb:.2f}GB"

        net_content = f"{net_sent}/{net_recv}"

        table.add_row(cpu_content, mem_content, disk_content, net_content)
        return table
