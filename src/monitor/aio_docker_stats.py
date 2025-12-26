import aiohttp
import asyncio
import docker
import orjson
from dataclasses import dataclass
from typing import Optional
from rich import box
from rich.table import Table
from rich.text import Text

from monitor import create_kv_grid, BORDER_STYLE, HEADER_STYLE
from monitor.aio_utils import format_bytes


@dataclass
class ContainerStats:
    id: str
    name: str
    cpu_percent: float
    cpu_limit: float
    mem_usage: int
    mem_limit: int
    mem_percent: float
    net_rx: int
    net_tx: int
    blk_read: int
    blk_write: int
    pids: int

    @property
    def cpu_str(self) -> str:
        return f"{self.cpu_percent:.2f}%"

    @property
    def cpu_limit_str(self) -> str:
        return f"{self.cpu_limit} C"

    @property
    def mem_usage_str(self) -> str:
        return format_bytes(self.mem_usage)

    @property
    def mem_limit_str(self) -> str:
        return format_bytes(self.mem_limit)

    @property
    def mem_percent_str(self) -> str:
        return f"{self.mem_percent:.2f}%"

    @property
    def mem_str(self):
        return f"{self.mem_percent_str} / {self.mem_usage_str}"

    @property
    def net_read_str(self) -> str:
        return f"{format_bytes(self.net_rx)}"

    @property
    def net_write_str(self) -> str:
        return f"{format_bytes(self.net_tx)}"

    @property
    def net_io_str(self) -> str:
        return f"{self.net_read_str} / {self.net_write_str}"

    @property
    def block_io_str(self) -> str:
        return f"{format_bytes(self.blk_read)} / {format_bytes(self.blk_write)}"


def calc_cpu_percent(stats):
    try:
        cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
                stats["cpu_stats"].get("system_cpu_usage", 0)
                - stats["precpu_stats"].get("system_cpu_usage", 0)
        )
        online_cpus = stats["cpu_stats"].get("online_cpus", 1)
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * online_cpus * 100
    except KeyError:
        pass
    return 0.0


def calc_mem_percent(stats):
    try:
        usage = stats["memory_stats"].get("usage", 0)
        limit = stats["memory_stats"].get("limit", 1)
        return (usage / limit) * 100 if limit else 0.0
    except KeyError:
        return 0.0


def get_cpu_limit(container_name):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        host_config = container.attrs['HostConfig']

        nano_cpus = host_config.get('NanoCpus', 0)
        if nano_cpus > 0:
            return nano_cpus / 1e9

        quota = host_config.get('CpuQuota', 0)
        period = host_config.get('CpuPeriod', 100000)
        if quota > 0:
            return quota / period
    except Exception:
        pass
    return None


async def process_container(cid: str, name: str, stats: dict, cpu_cores: Optional[float]) -> Optional[ContainerStats]:
    if not stats:
        return None

    # CPU
    cpu_pct = calc_cpu_percent(stats)
    online_cpus = stats.get("cpu_stats", {}).get("online_cpus", 1) if cpu_cores is None else cpu_cores

    # Memory
    mem_stats = stats.get("memory_stats", {})
    mem_usage = mem_stats.get("usage", 0)
    mem_limit = mem_stats.get("limit", 0)
    mem_pct = calc_mem_percent(stats)

    # Net I/O
    rx = tx = 0
    networks = stats.get("networks")
    if networks:
        for iface in networks.values():
            rx += iface.get("rx_bytes", 0)
            tx += iface.get("tx_bytes", 0)

    # Block I/O
    rd = wr = 0
    blkio = stats.get("blkio_stats", {})
    if blkio:
        io_service_bytes_recursive = blkio.get("io_service_bytes_recursive", [])
        if io_service_bytes_recursive:
            for entry in io_service_bytes_recursive:
                op = entry.get("op")
                if op == "Read":
                    rd += entry.get("value", 0)
                elif op == "Write":
                    wr += entry.get("value", 0)

    pids = stats.get("pids_stats", {}).get("current", 0)

    return ContainerStats(
        id=cid[:12],
        name=name,
        cpu_percent=cpu_pct,
        cpu_limit=online_cpus,
        mem_usage=mem_usage,
        mem_limit=mem_limit,
        mem_percent=mem_pct,
        net_rx=rx,
        net_tx=tx,
        blk_read=rd,
        blk_write=wr,
        pids=pids
    )


CONTAINER_CORE_NAME = "brainframe-core-1"


class AioDockerStats:
    def __init__(self):
        self.connector = aiohttp.UnixConnector(path="/var/run/docker.sock")
        self.session = None
        self.event_watcher = None
        self.active_tasks = {}
        self.stats_cache: dict[str, ContainerStats] = {}

    async def start(self):
        timeout = aiohttp.ClientTimeout(total=None)
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout
        )
        self.event_watcher = asyncio.create_task(self.polling_containers())

    async def close(self):
        if self.session:
            await self.session.close()
        if self.event_watcher:
            self.event_watcher.cancel()

    async def polling_containers(self):
        while True:
            try:
                containers = await self.list_containers()
                containers_map = {}
                for c in containers:
                    name = c["Names"][0].lstrip("/")
                    containers_map[name] = True
                    if name not in self.active_tasks:
                        cpu_cores = get_cpu_limit(name)
                        cid = c["Id"]
                        self.active_tasks[name] = asyncio.create_task(
                            self.stream_container_stats(cid, name, cpu_cores)
                        )

                active_tasks_keys = list(self.active_tasks.keys())
                for name in active_tasks_keys:
                    if name not in containers_map:
                        task = self.active_tasks.pop(name, None)
                        if task:
                            task.cancel()
            except Exception as e:
                print(f"Polling error: {str(e)}")
                continue
            finally:
                await asyncio.sleep(3.0)

    async def list_containers(self):
        async with self.session.get("http://docker/containers/json") as resp:
            return await resp.json()

    async def stream_container_stats(self, cid, name, cpu_cores):
        url = f"http://docker/containers/{cid}/stats?stream=true"
        try:
            async with self.session.get(url) as resp:
                async for line in resp.content:
                    if not line: continue
                    stats_json = orjson.loads(line.decode())
                    processed = await process_container(cid, name, stats_json, cpu_cores)
                    if processed:
                        self.stats_cache[name] = processed
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            print(f"Stream error for {name}: {ex}")
        finally:
            self.stats_cache.pop(name, None)

    async def basic_stats_grid(self):
        stats = self.stats_cache.get(CONTAINER_CORE_NAME)
        if not stats:
            return create_kv_grid(title=f"Containers", rows=[])

        tot_cpu, tot_mem = 0, 0
        for item in list(self.stats_cache.values()):
            tot_cpu += item.cpu_percent
            tot_mem += item.mem_usage

        # Example of how easy it is to access data now:
        rows = [
            (f"Core CPU", stats.cpu_str),
            (f"Core MEM", stats.mem_str),
            (f"Core Net-I", stats.net_read_str),
            (f"Core Net-O", stats.net_write_str),
            (f"Total CPU", f"{tot_cpu:.2f}%"),
            (f"Total MEM", format_bytes(tot_mem)),
        ]

        return create_kv_grid(title=f"Containers[Core: {stats.cpu_limit_str} / {stats.mem_limit_str}]", rows=rows)

    async def stats_table(self):
        table = Table(
            box=box.ASCII,
            expand=True,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        table.add_column("ID", justify="left", max_width=12, style="dim")
        table.add_column("NAME", justify="left", overflow="ellipsis")
        table.add_column("CPU % / LIMIT", justify="right")
        table.add_column("MEM USAGE / LIMIT / MEM %", justify="right")
        table.add_column("NETWORK I/O", justify="right", style="dim")
        table.add_column("BLOCK I/O", justify="right", style="dim")
        table.add_column("PIDS", justify="right", style="dim")

        for stats in self.stats_cache.values():
            cpu_style = "red" if stats.cpu_percent > 80.0 else "green"

            table.add_row(
                stats.id,
                stats.name,
                Text(f"{stats.cpu_str} / {stats.cpu_limit_str}", style=cpu_style),
                f"{stats.mem_usage_str} / {stats.mem_limit_str} / {stats.mem_percent_str}",
                stats.net_io_str,
                stats.block_io_str,
                str(stats.pids)
            )

        return table
