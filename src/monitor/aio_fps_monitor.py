import math
import time
from collections import deque
from typing import Optional

import aiohttp
import asyncio

from dataclasses import dataclass
import statistics

import orjson
from rich import box
from rich.table import Table

from monitor import BORDER_STYLE, HEADER_STYLE, HISTORY_SIZE


class FpsStatItem:
    def __init__(self, history_size):
        self.latest_second = 0
        self.fps = 0
        self.latest_committed_fps = 0
        self.history_size = history_size
        self.fps_history = deque([0] * self.history_size, maxlen=self.history_size)

    # Based on the received timestamp
    def put(self, current_second, count=1):
        # Accumulate
        if self.latest_second == current_second:
            self.fps += count
            return

        if self.latest_second != 0 and current_second - self.latest_second > 1:
            for i in range(current_second - self.latest_second - 1):
                self.fps_history.append(0)
        self.latest_committed_fps = self.fps
        self.fps_history.append(self.latest_committed_fps)
        self.latest_second = current_second
        self.fps = count

    def get_history_stat(self):
        median = statistics.median(self.fps_history)
        minimum = min(self.fps_history)
        maximum = max(self.fps_history)
        average = sum(self.fps_history) / self.history_size
        return median, minimum, maximum, average


@dataclass
class ExtStreamConf:
    id: int
    name: str
    stream_url: str
    analysis: str
    fps: float
    buf: list


class AioFpsMonitor:
    def __init__(self, server_url, history_size=HISTORY_SIZE):
        self.server_url = server_url
        self.history_size = history_size
        self.tot_stat = FpsStatItem(history_size)
        self.streams_stat = {}
        self.ext_streams = []
        self.session = None
        self.task_polling_stream_configurations = None
        self.task_streams_statuses = None

    async def start(self):
        timeout = aiohttp.ClientTimeout(total=None)
        self.session = aiohttp.ClientSession(base_url=self.server_url, timeout=timeout)
        self.task_polling_stream_configurations = asyncio.create_task(self.polling_stream_configurations())
        self.task_streams_statuses = asyncio.create_task(self.streams_statuses())

    async def close(self):
        if self.task_streams_statuses:
            self.task_streams_statuses.cancel()
        if self.task_polling_stream_configurations:
            self.task_polling_stream_configurations.cancel()
        if self.session:
            await self.session.close()

    async def polling_stream_configurations(self):
        while True:
            self.ext_streams = await self.list_streams()
            await asyncio.sleep(delay=3.0)

    async def list_streams(self):
        ext_streams = []
        async with self.session.get("/api/streams") as resp:
            streams = await resp.json()

        for stream in streams:
            stream_id = stream.get("id")
            async with self.session.get(f"/api/streams/{stream_id}/analyze") as resp:
                analysis = await  resp.json()

            a_k = "T" if analysis else "K"

            ext_stream = ExtStreamConf(id=stream.get("id"), name=stream.get("name"), stream_url="", analysis=a_k, fps=0, buf=[])
            ext_streams.append(ext_stream)

        return ext_streams

    async def streams_statuses(self):
        streams_tstamp_map = {}
        async with self.session.get("/api/streams/statuses") as resp:
            async for line in resp.content:
                if not line: continue
                zone_status_packet = orjson.loads(line)
                # print(zone_status_packet)
                current_second = math.ceil(time.time())
                received_count = 0
                for stream_id in zone_status_packet.keys():
                    zone_statuses = zone_status_packet.get(stream_id)

                    if not zone_statuses: continue

                    stream_id = int(stream_id)
                    tstamp = zone_statuses.get("Screen").get("tstamp")

                    previous_tstamp = streams_tstamp_map.get(stream_id, 0)
                    if tstamp <= previous_tstamp:
                        continue
                    streams_tstamp_map[stream_id] = tstamp
                    received_count += 1

                    if stream_id not in self.streams_stat:
                        self.streams_stat[stream_id] = FpsStatItem(self.history_size)
                    stream_stat: FpsStatItem = self.streams_stat[stream_id]
                    stream_stat.put(current_second=current_second)

                self.tot_stat.put(current_second=current_second, count=received_count)

    def get_stat(self):
        # median, minimum, maximum, average
        return self.tot_stat.get_history_stat()

    async def get_stat_table_latest(self):
        table = Table(
            box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1), collapse_padding=True, show_lines=True, expand=True,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        # Define columns
        table.add_column("LATEST", justify="center", style="white")

        # Add the data row
        table.add_row(f"{self.tot_stat.latest_committed_fps:.2f}")
        return table

    async def get_stat_table_throughout(self):
        table = Table(
            box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1), collapse_padding=True, show_lines=True, expand=True,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        # Define columns
        table.add_column("MED", justify="center", style="white")
        table.add_column("AVG", justify="center", style="white")
        table.add_column("MIN", justify="center", style="white")
        table.add_column("MAX", justify="center", style="white")

        # Add the data row

        median, minimum, maximum, average = self.tot_stat.get_history_stat()
        table.add_row(f"{median:.2f}", f"{average:.2f}", f"{minimum:.2f}", f"{maximum:.2f}")
        return table

    async def get_stat_table_streams(self):
        table = Table(
            box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1), collapse_padding=True, show_lines=True, expand=True,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )

        # Define columns
        table.add_column("AVG", justify="center", style="white")
        table.add_column("MIN", justify="center", style="white")
        table.add_column("MAX", justify="center", style="white")

        # Add the data row
        # streams = copy.deepcopy(self.streams_stat)
        streams_fps = [x.latest_committed_fps for x in self.streams_stat.values()]
        if len(streams_fps) == 0:
            fps, minimum, maximum, average = 0, 0, 0, 0
        else:
            fps = sum(streams_fps)
            minimum = min(streams_fps)
            maximum = max(streams_fps)
            average = fps / len(streams_fps)

        table.add_row(f"{average:.2f}", f"{minimum:.2f}", f"{maximum:.2f}")
        return table

    async def get_detailed_streams_table(self):
        table = Table(
            title="Status of streams",
            title_style="white",
            box=box.ROUNDED,
            expand=True,
            show_lines=False,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )
        table.add_column("A/K", justify="right", style="dim")
        table.add_column("sID", justify="left", no_wrap=True, max_width=2, style="dim")
        table.add_column("NAME", justify="left", overflow="ellipsis", style="dim")
        # table.add_column("Stream URL", justify="right")
        table.add_column("FPS", justify="right")
        # table.add_column("[Buf, Age, Dsync, Drift]", justify="right")

        ext_streams = list(self.ext_streams)
        for ext_stream in ext_streams:
            fps_item: Optional[FpsStatItem] = self.streams_stat.get(ext_stream.id)
            if fps_item is None:
                fps = 0
            else:
                fps = fps_item.latest_committed_fps

            table.add_row(
                ext_stream.analysis,
                f"{ext_stream.id}",
                ext_stream.name,
                f"{fps:.2f}",
            )
        return table
