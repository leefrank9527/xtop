def format_bytes(num: float) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if num < 1024:
            return f"{num:.2f}{unit}"
        num /= 1024
    return f"{num:.2f}PiB"


def format_net_speed(bytes_per_sec):
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f}KB/s"
    return f"{bytes_per_sec / (1024 * 1024):.1f}MB/s"
