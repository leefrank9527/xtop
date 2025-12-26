import asyncio
import time
from collections import deque
from dataclasses import dataclass

import psutil

from monitor import HISTORY_SIZE, create_kv_grid

from monitor.aio_utils import format_bytes, format_net_speed


@dataclass
class SystemResourceItem:
    total: float
    percent: float
    used: float


zero_item = SystemResourceItem(0, 0, 0)


@dataclass
class SystemUsageStats:
    tstamp: float = time.time()
    cpu_info: SystemResourceItem = zero_item
    mem_info: SystemResourceItem = zero_item
    disk_info: SystemResourceItem = zero_item
    load_avg: tuple[float, float, float] = (0, 0, 0)
    network_read: float = 0
    network_write: float = 0
    network_read_speed: float = 0
    network_write_speed: float = 0


class AioSystemUsage:
    def __init__(self, history_size=HISTORY_SIZE):
        self.history_size = history_size

        # History Deques
        self.system_usage_history = deque([SystemUsageStats()] * history_size, maxlen=history_size)

        # State Variables
        self.stats = SystemUsageStats()

        self.task_event_loop = None

    async def start(self):
        self.task_event_loop = asyncio.create_task(self._event_loop())

    async def close(self):
        if self.task_event_loop:
            self.task_event_loop.cancel()

    async def _event_loop(self):
        while True:
            stats = SystemUsageStats(tstamp=time.time())

            # 1. CPU
            cpu_pct = psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count(logical=True)
            stats.cpu_info = SystemResourceItem(total=cpu_count, percent=cpu_pct, used=cpu_pct * cpu_count)

            if hasattr(psutil, "getloadavg"):
                stats.load_avg = psutil.getloadavg()

            # 2. Memory
            mem_info = psutil.virtual_memory()
            stats.mem_info = SystemResourceItem(total=mem_info.total, percent=mem_info.percent, used=mem_info.used)

            # 3. Disk
            disk_info = psutil.disk_usage('/')
            stats.disk_info = SystemResourceItem(total=disk_info.total, percent=disk_info.percent, used=disk_info.used)

            # 4. Network
            net_io = psutil.net_io_counters()
            stats.network_read = net_io.bytes_recv
            stats.network_write = net_io.bytes_sent

            time_delta = stats.tstamp - self.stats.tstamp

            if time_delta > 0.0:
                stats.network_read_speed = (stats.network_read - self.stats.network_read) / time_delta
                stats.network_write_speed = (stats.network_write - self.stats.network_write) / time_delta

            self.stats = stats
            self.system_usage_history.append(stats)

            sleep_time = max(0.1, 1 - time_delta)
            await asyncio.sleep(delay=sleep_time)

    @property
    def cpu_history(self):
        # Create a list copy to avoid modification during iteration issues
        data = [e.cpu_info.percent for e in list(self.system_usage_history)]
        return data

    @property
    def mem_history(self):
        # Create a list copy to avoid modification during iteration issues
        data = [e.mem_info.percent for e in list(self.system_usage_history)]
        return data

    async def get_cpu_stat(self):
        data = self.cpu_history
        return min(data), max(data), sum(data) / len(data)

    async def get_mem_stat(self):
        data = self.mem_history
        return min(data), max(data), sum(data) / len(data)

    async def get_stat(self):
        # CPU Content
        cpu_count_str = f"{self.stats.cpu_info.total}C"
        cpu_content = f"{self.stats.cpu_info.percent * self.stats.cpu_info.total:.2f}%"

        # Memory Content (GB + History Stats)
        mem_total_str = format_bytes(self.stats.mem_info.total)
        mem_content = f"{self.stats.mem_info.percent:.2f}%/{format_bytes(self.stats.mem_info.used)}"

        # Disk Stats
        disk_total_str = format_bytes(self.stats.disk_info.total)
        disk_content = f"{self.stats.disk_info.percent:.2f}%/{format_bytes(self.stats.disk_info.used)}"

        # Network Stats
        net_sent = format_net_speed(self.stats.network_write_speed)
        net_recv = format_net_speed(self.stats.network_read_speed)
        net_content = f"{net_sent}/{net_recv}"

        return cpu_count_str, cpu_content, mem_total_str, mem_content, disk_total_str, disk_content, net_content

    async def get_stat_grid(self):
        cpu_count_str, cpu_content, mem_total_str, mem_content, disk_total_str, disk_content, net_content = await self.get_stat()
        rows = [(f"CPU:{cpu_count_str}", cpu_content), (f"Mem: {mem_total_str}", mem_content), (f"Disk: {disk_total_str}", disk_content), ("Network(UP/Down)", net_content)]
        return create_kv_grid("System", rows)
