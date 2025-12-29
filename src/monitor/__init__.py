from dataclasses import dataclass
from typing import Optional

from rich import box
from rich.table import Table
from rich.text import Text

HISTORY_SIZE = 60

# BORDER_STYLE = "rgb(96,96,96)"
BORDER_STYLE = "green"
TICKS_COLOR = "green"
# HEADER_STYLE = "magenta"
HEADER_STYLE = "green"
TITLE_STYLE = "bold green"
WHITE = "\033[37m"
RESET = "\033[0m"


def format_bytes(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.2f}{unit}"
        num /= 1024
    return f"{num:.2f}PB"


def format_net_speed(bytes_per_sec):
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f}KB"
    return f"{bytes_per_sec / (1024 * 1024):.1f}MB"


@dataclass
class ResourceItem:
    total: float
    percent: float
    used: float


zero_item = ResourceItem(0, 0, 0)


class ResourceStats:
    def __init__(self, tstamp=0):
        self.tstamp: float = 0
        self.cpu_info: ResourceItem = zero_item
        self.mem_info: ResourceItem = zero_item
        self.disk_info: ResourceItem = zero_item
        self.load_avg: tuple[float, float, float] = (0, 0, 0)
        self.network_read: float = 0
        self.network_write: float = 0
        self.network_read_speed: float = 0
        self.network_write_speed: float = 0

    @property
    def cpu_str(self) -> str:
        return f"{self.cpu_info.percent:.2f}%"

    @property
    def cpu_long_str(self) -> str:
        return f"{self.cpu_info.percent * self.cpu_info.total:.2f}%"

    @property
    def cpu_limit_str(self) -> str:
        return f"{self.cpu_info.total}C"

    @property
    def mem_usage_str(self) -> str:
        return format_bytes(self.mem_info.used)

    @property
    def mem_limit_str(self) -> str:
        return format_bytes(self.mem_info.total)

    @property
    def mem_percent_str(self) -> str:
        return f"{self.mem_info.percent:.2f}%"

    @property
    def mem_str(self):
        return f"{self.mem_percent_str} / {self.mem_usage_str}"

    @property
    def network_read_speed_str(self) -> str:
        return format_net_speed(self.network_read_speed)

    @property
    def network_write_speed_str(self) -> str:
        return format_net_speed(self.network_write_speed)

    @property
    def network_str(self):
        return f"{self.network_read_speed_str} / {self.network_write_speed_str}"

    @property
    def disk_usage_str(self) -> str:
        return format_bytes(self.disk_info.used)

    @property
    def disk_limit_str(self) -> str:
        return format_bytes(self.disk_info.total)

    @property
    def disk_percent_str(self) -> str:
        return f"{self.disk_info.percent:.2f}%"

    @property
    def disk_str(self):
        return f"{self.disk_percent_str} / {self.disk_usage_str}"


def create_kv_grid(title: str, rows: list) -> Table:
    grid = Table.grid(expand=True)

    grid.add_column(Text(title, style=TITLE_STYLE), justify="left", ratio=1)
    grid.add_column("", justify="right", ratio=2)

    for key, value in rows:
        grid.add_row(Text(key, style="bold cyan"), f"{value}")

    return grid


def create_table(title: Optional[str]):
    t = Table(
        title=Text(title, style=TITLE_STYLE),
        title_justify="left",
        show_header=True,
        box=box.SIMPLE,
        expand=True,
        show_lines=False,
        header_style=HEADER_STYLE,
        border_style=BORDER_STYLE
    )
    return t


def create_basic_table(title: Optional[str] = None):
    if title is None:
        t = Table(
            show_header=True,
            box=box.SIMPLE,
            expand=True,
            show_lines=False,
            header_style=HEADER_STYLE,
            border_style=BORDER_STYLE
        )
        return t
    else:
        return create_table(title)
