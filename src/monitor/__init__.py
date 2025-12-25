from rich import box
from rich.align import Align
from rich.table import Table
from rich.text import Text

HISTORY_SIZE = 60

# BORDER_STYLE = "rgb(96,96,96)"
BORDER_STYLE = "black"
TICKS_COLOR = "cyan"
# HEADER_STYLE = "magenta"
HEADER_STYLE = "cyan"
TITLE_STYLE = "bold green"
WHITE = "\033[37m"
RESET = "\033[0m"


def create_kv_grid(title: str, rows: list) -> Table:
    # grid = Table.grid(expand=True)
    # title = Text(title, style=TITLE_STYLE),
    # title_justify = "left",
    grid = Table(
        show_header=True,
        box=box.SIMPLE_HEAD,
        expand=True,
        show_lines=False,
        header_style=HEADER_STYLE,
        border_style=BORDER_STYLE
    )
    grid.add_column(Text(title, style=TITLE_STYLE), justify="left", ratio=1)
    grid.add_column("", justify="right", ratio=1)

    for key, value in rows:
        grid.add_row(Text(key, style="bold cyan"), f"{value}")

    return grid
