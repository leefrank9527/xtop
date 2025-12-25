import aiohttp
import asyncio
import docker
import orjson
from rich import box
from rich.table import Table
from rich.text import Text

from monitor import BORDER_STYLE, HEADER_STYLE, create_kv_grid


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


def format_bytes(num):
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}PiB"


def get_cpu_limit(container_name):
    client = docker.from_env()
    container = client.containers.get(container_name)
    host_config = container.attrs['HostConfig']

    cpu_cores = None

    # 1. Check NanoCpus
    nano_cpus = host_config.get('NanoCpus', 0)
    if nano_cpus > 0:
        cpu_cores = nano_cpus / 1e9
    # 2. Check Quota/Period (if NanoCpus is 0)
    else:
        quota = host_config.get('CpuQuota', 0)
        period = host_config.get('CpuPeriod', 100000)
        if quota > 0:
            cpu_cores = quota / period

    return cpu_cores


async def process_container(cid, name, stats, cpu_cores):
    if not stats:
        return None

    short_id = cid[:12]

    cpu = calc_cpu_percent(stats)

    # 2. Extract CPU Limit (Online CPUs)
    # This usually represents the number of cores available to the container
    online_cpus = stats.get("cpu_stats", {}).get("online_cpus", 1) if cpu_cores is None else cpu_cores

    # Safe dictionary gets
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
        if io_service_bytes_recursive is not None:
            for entry in io_service_bytes_recursive:
                op = entry.get("op")
                if op == "Read":
                    rd += entry.get("value", 0)
                elif op == "Write":
                    wr += entry.get("value", 0)

    pids = stats.get("pids_stats", {}).get("current", 0)

    return [
        short_id,
        name,
        f"{cpu:.2f}%",
        f"{online_cpus} C",  # Add to data list
        f"{format_bytes(mem_usage)}",
        f"{format_bytes(mem_limit)}",
        f"{mem_pct:.2f}%",
        f"{format_bytes(rx)} / {format_bytes(tx)}",
        f"{format_bytes(rd)} / {format_bytes(wr)}",
        pids
    ]


CONTAINER_CORE_NAME = "brainframe-core-1"


class AioDockerStats:
    def __init__(self):
        self.connector = aiohttp.UnixConnector(path="/var/run/docker.sock")
        self.session = None
        self.event_watcher = None
        self.active_tasks = {}
        self.stats_cache = {}

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
            # 1. Initial Load: Get all currently running containers
            containers = await self.list_containers()
            containers_map = {}
            for c in containers:
                name = c["Names"][0].lstrip("/")
                containers_map[name] = True
                if name in self.active_tasks:
                    continue
                cpu_cores = get_cpu_limit(container_name=name)
                cid = c["Id"]
                self.active_tasks[name] = asyncio.create_task(
                    self.stream_container_stats(cid, name, cpu_cores)
                )

            active_tasks_keys = list(self.active_tasks.keys())
            for name in active_tasks_keys:
                if name not in containers_map:
                    task = self.active_tasks.pop(name, None)
                    if task is not None:
                        task.cancle()
            await asyncio.sleep(delay=3.0)

    async def list_containers(self):
        async with self.session.get("http://docker/containers/json") as resp:
            return await resp.json()

    async def stream_container_stats(self, cid, name, cpu_cores):
        """Task that streams stats for a single container."""
        url = f"http://docker/containers/{cid}/stats?stream=true"
        try:
            async with self.session.get(url) as resp:
                async for line in resp.content:
                    if not line: continue
                    stats = orjson.loads(line.decode())
                    # print(stats)
                    self.stats_cache[name] = await  process_container(cid, name, stats, cpu_cores)
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            print(ex)
        finally:
            self.stats_cache.pop(cid, None)

    async def basic_core_stats_grid(self):
        core_row = self.stats_cache.get(CONTAINER_CORE_NAME, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        cpu_count = core_row[3]
        cpu_percent = core_row[2]
        mem_limitation = core_row[5]
        mem_percent = core_row[4]
        mem_usage = core_row[6]
        net_io = core_row[7]

        rows = [(f"CPU: {cpu_count}", cpu_percent), (f"MEM: {mem_limitation}", f"{mem_percent} / {mem_usage}"), ("NET I/O", net_io)]
        grid = None
        try:
            grid = create_kv_grid(title="Container[Core]", rows=rows)
        except Exception as ex:
            print(ex)
        return cpu_count, cpu_percent, mem_limitation, mem_percent, mem_usage, net_io, grid

    async def stats_table(self):
        table = Table(
            title=None,
            box=box.ROUNDED,
            expand=True,
            show_lines=False,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        table.add_column("ID", justify="left", no_wrap=True, max_width=12, style="dim")
        table.add_column("NAME", justify="left", overflow="ellipsis", style="dim")
        table.add_column("CPU % / LIMIT", justify="right")
        table.add_column("MEM USAGE / LIMIT / MEM %", justify="right", style="dim")
        table.add_column("NET I/O", justify="right", style="dim")
        table.add_column("BLOCK I/O", justify="right", style="dim")
        table.add_column("PIDS", justify="right", style="dim")

        latest_stats = list(self.stats_cache.values())
        for row in latest_stats:
            # row is [id, name, cpu, cpu_limit, mem_usage, mem_pct, net, block, pids]
            # Color logic for high CPU usage
            cpu_val = row[2]
            try:
                cpu_num = float(cpu_val.strip('%'))
                cpu_style = "red" if cpu_num > 80.0 else "green"
            except ValueError:
                cpu_style = "green"

            table.add_row(
                row[0],  # ID
                row[1],  # Name
                Text(f"{row[2]} / {row[3]}", style=cpu_style),  # CPU %
                f"{row[4]} / {row[5]} / {row[6]}",  # Mem Usage
                row[7],  # Net
                row[8],  # Block
                str(row[9])  # PIDS
            )

        return table


async def main():
    stat = AioDockerStats()
    # await  stat.start()
    # event_watcher = asyncio.create_task(stat.polling_containers())
    await asyncio.gather(stat.event_watcher, return_exceptions=True)
    await  stat.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
