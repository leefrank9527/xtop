import math
import time
from collections import deque
from typing import Optional

import aiohttp
import asyncio

from dataclasses import dataclass
import statistics

import orjson
from rich.text import Text

from monitor import HEADER_STYLE, HISTORY_SIZE, create_kv_grid, create_basic_table, create_table


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

    def get_stat_latest(self):
        return f"{self.tot_stat.latest_committed_fps:.2f}"

    def get_stat_throughout(self):
        median, minimum, maximum, average = self.tot_stat.get_history_stat()
        return f"{median:.2f}", f"{minimum:.2f}", f"{maximum:.2f}", f"{average:.2f}"

    def get_stat_streams(self):
        streams_fps = [x.latest_committed_fps for x in self.streams_stat.values()]
        if len(streams_fps) == 0:
            fps, minimum, maximum, average = 0, 0, 0, 0
        else:
            fps = sum(streams_fps)
            minimum = min(streams_fps)
            maximum = max(streams_fps)
            average = fps / len(streams_fps)

        return f"{fps:.2f}", f"{average:.2f}", f"{minimum:.2f}", f"{maximum:.2f}"

    async def get_stat_throughout_grid(self):
        median, minimum, maximum, average = self.get_stat_throughout()
        rows = [("Latest", f"{self.tot_stat.latest_committed_fps:.2f}"), ("Med", median), ("Min", minimum), ("Max", maximum), ("Avg", average)]
        return create_kv_grid("Fps Throughout", rows)

    async def get_stat_streams_grid(self):
        fps, average, minimum, maximum = self.get_stat_streams()
        rows = [("Sum", fps), ("Min", minimum), ("Max", maximum), ("Avg", average)]
        return create_kv_grid("Fps Streams", rows)

    async def add_stat_throughout(self, grid):
        median, minimum, maximum, average = self.get_stat_throughout()
        grid.add_row(
            Text("Throughout", style=HEADER_STYLE),
            f"{self.tot_stat.latest_committed_fps:.2f}",
            average,
            minimum,
            maximum,
        ),
        return grid

    async def add_stat_streams(self, grid):
        fps, average, minimum, maximum = self.get_stat_streams()
        grid.add_row(
            Text("Streams", style=HEADER_STYLE),
            fps,
            average,
            minimum,
            maximum,
        ),
        return grid

    async def render_basic_stats(self):
        t = create_basic_table("FPS")

        t.add_column("Metrics", justify="left", ratio=2)
        t.add_column("Latest", justify="right", ratio=1)
        t.add_column("Avg", justify="right", ratio=1)
        t.add_column("Min", justify="right", ratio=1)
        t.add_column("Max", justify="right", ratio=1)

        await self.add_stat_throughout(t)
        await self.add_stat_streams(t)

        return t

    async def render_detailed_streams_status(self):
        table = create_table("Status of streams")
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
