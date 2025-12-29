import time

import aiohttp
import asyncio
import docker
import orjson
from typing import Optional
from rich.text import Text

from monitor import HEADER_STYLE, ResourceStats, ResourceItem, format_bytes, format_net_speed, create_table


class DockerContainerResourceStats(ResourceStats):
    def __init__(self, tstamp: float = 0, id: str = "", name: str = ""):
        super().__init__(tstamp=tstamp)
        self.id: str = id
        self.name: str = name
        self.blk_read: int = 0
        self.blk_write: int = 0
        self.pids: int = 0

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


async def process_container(cid: str, name: str, perf_info: dict, cpu_cores: Optional[float], previous_stats: DockerContainerResourceStats) -> Optional[DockerContainerResourceStats]:
    if not perf_info:
        return None

    stats = DockerContainerResourceStats(tstamp=time.time(), id=cid, name=name)

    # CPU
    cpu_pct = calc_cpu_percent(perf_info)
    online_cpus = perf_info.get("cpu_stats", {}).get("online_cpus", 1) if cpu_cores is None else cpu_cores

    stats.cpu_info = ResourceItem(total=online_cpus, percent=cpu_pct, used=0)

    # Memory
    mem_stats = perf_info.get("memory_stats", {})
    mem_usage = mem_stats.get("usage", 0)
    mem_limit = mem_stats.get("limit", 0)
    mem_pct = calc_mem_percent(perf_info)

    stats.mem_info = ResourceItem(total=mem_limit, percent=mem_pct, used=mem_usage)

    # Net I/O
    rx = tx = 0
    networks = perf_info.get("networks")
    if networks:
        for iface in networks.values():
            rx += iface.get("rx_bytes", 0)
            tx += iface.get("tx_bytes", 0)

    stats.network_read = rx
    stats.network_write = tx

    time_delta = stats.tstamp - previous_stats.tstamp
    if time_delta > 0:
        stats.network_read_speed = (stats.network_read - previous_stats.network_read) / time_delta
        stats.network_write_speed = (stats.network_write - previous_stats.network_write) / time_delta

    # Block I/O
    rd = wr = 0
    blkio = perf_info.get("blkio_stats", {})
    if blkio:
        io_service_bytes_recursive = blkio.get("io_service_bytes_recursive", [])
        if io_service_bytes_recursive:
            for entry in io_service_bytes_recursive:
                op = entry.get("op")
                if op == "Read":
                    rd += entry.get("value", 0)
                elif op == "Write":
                    wr += entry.get("value", 0)
    stats.blk_read = rd
    stats.blk_write = wr
    stats.pids = perf_info.get("pids_stats", {}).get("current", 0)

    return stats


CONTAINER_CORE_NAME = "brainframe-core-1"


class AioDockerStats:
    def __init__(self):
        self.connector = aiohttp.UnixConnector(path="/var/run/docker.sock")
        self.session = None
        self.event_watcher = None
        self.active_tasks = {}
        self.stats_cache: dict[str, DockerContainerResourceStats] = {}

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
                        cid = c["Id"][0:12]
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
                    prev_stats = self.stats_cache.get(name, DockerContainerResourceStats(tstamp=time.time()))
                    processed = await process_container(cid, name, stats_json, cpu_cores, previous_stats=prev_stats)
                    if processed:
                        self.stats_cache[name] = processed
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            print(f"Stream error for {name}: {ex}")
        finally:
            self.stats_cache.pop(name, None)

    async def render_basic_stats_row_core(self, t):
        stats = self.stats_cache.get(CONTAINER_CORE_NAME)
        if not stats:
            return t
        t.add_row(
            Text(f"Core: {stats.cpu_limit_str}/{stats.mem_limit_str}", style=HEADER_STYLE),
            stats.cpu_str,
            stats.mem_str,
            stats.network_str,
            "/",
        )
        return t

    async def render_basic_stats_row_all(self, t):
        tot_cpu_used, tot_mem_used, tot_read_speed, tot_write_speed = 0, 0, 0, 0
        for item in list(self.stats_cache.values()):
            tot_cpu_used += item.cpu_info.percent
            tot_mem_used += item.mem_info.used
            tot_read_speed += item.network_read_speed
            tot_write_speed += item.network_write_speed
        t.add_row(
            Text("All Containers", style=HEADER_STYLE),
            f"{tot_cpu_used:.2f}%",
            format_bytes(tot_mem_used),
            f"{format_net_speed(tot_read_speed)} / {format_net_speed(tot_write_speed)}",
            "/",
        )
        return t

    async def render_stats_table(self):
        table = create_table("Docker Container Stats")

        table.add_column("ID", justify="left", max_width=12, style="dim")
        table.add_column("NAME", justify="left", overflow="ellipsis")
        table.add_column("CPU %/LIMIT", justify="right")
        table.add_column("MEM %/USED/LIMIT", justify="right")
        table.add_column("NETWORK I/O(S)", justify="right", style="dim")
        # table.add_column("BLOCK I/O", justify="right", style="dim")
        table.add_column("PIDS", justify="right", style="dim")

        for stats in self.stats_cache.values():
            cpu_style = "red" if stats.cpu_info.percent > 80.0 else "green"

            table.add_row(
                stats.id,
                stats.name,
                Text(f"{stats.cpu_str}/{stats.cpu_limit_str}", style=cpu_style),
                f"{stats.mem_percent_str}/{stats.mem_usage_str}/{stats.mem_limit_str}",
                stats.network_str,
                # stats.block_io_str,
                str(stats.pids)
            )

        return table
