"""Console Notifier with developer-focused terminal color formatting."""

import sys
from server.notifier.base import BaseNotifier
from server.schemas import DownloadState, PushPayload

# Reconfigure stdout for UTF-8 on Windows if possible
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ANSI Color Codes (Matching Render-inspired Dark Terminal Theme)
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_PURPLE = "\033[38;2;138;5;255m"     # #8a05ff
CLR_LAVENDER = "\033[38;2;192;132;252m" # #c084fc
CLR_GREEN = "\033[38;2;97;207;146m"     # #61cf92
CLR_WHITE = "\033[38;2;255;255;255m"
CLR_GRAY = "\033[38;2;113;113;122m"     # #71717a
CLR_YELLOW = "\033[38;2;251;191;36m"
CLR_RED = "\033[38;2;248;113;113m"


def format_bytes(num_bytes: int | float | None) -> str:
    """Formats bytes into human readable MB/GB."""
    if num_bytes is None:
        return "?"
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def format_speed(bytes_per_sec: int) -> str:
    """Formats speed in bytes/sec to KB/s or MB/s."""
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    if bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    return f"{bytes_per_sec} B/s"


def format_eta(seconds: int | None) -> str:
    """Formats seconds remaining into human readable m/s string."""
    if seconds is None:
        return "--"
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m left"
    if seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s left"
    return f"{seconds}s left"


class ConsoleNotifier(BaseNotifier):
    """Outputs live download progress snapshots to terminal stdout."""

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stdout

    async def notify(self, payload: PushPayload) -> None:
        time_str = payload.sent_at.strftime("%H:%M:%S")
        prefix = (
            f"{CLR_PURPLE}[SEQ #{payload.seq:03d} | {time_str}]{CLR_RESET} "
            f"{CLR_DIM}from {payload.source}@{payload.pc_name}:{CLR_RESET}"
        )

        if not payload.downloads:
            print(f"{prefix} {CLR_GRAY}// no active transfers{CLR_RESET}", file=self.stream)
            return

        lines = [prefix]
        for dl in payload.downloads:
            state_tag = self._format_state(dl.state)
            pct_str = f"{dl.percentage:>5.1f}%" if dl.percentage is not None else "  ? %"
            pct_colored = f"{CLR_GREEN}{pct_str}{CLR_RESET}"
            curr_str = format_bytes(dl.bytes_downloaded)
            total_str = format_bytes(dl.total_bytes)
            speed_str = f"{CLR_GREEN}{format_speed(dl.speed):>9}{CLR_RESET}"
            eta_str = f"{CLR_LAVENDER}{format_eta(dl.eta_seconds):>10}{CLR_RESET}"
            name_str = f"{CLR_BOLD}{CLR_WHITE}{dl.filename[:28]:<28}{CLR_RESET}"

            line = (
                f"  {state_tag} {name_str} {pct_colored} "
                f"[{curr_str:>8} / {total_str:<8}] {speed_str} {eta_str}"
            )
            lines.append(line)

        try:
            print("\n".join(lines), file=self.stream)
        except UnicodeEncodeError:
            # Fallback for strict ASCII encodings
            clean_lines = [line.encode("ascii", errors="replace").decode("ascii") for line in lines]
            print("\n".join(clean_lines), file=self.stream)

    def _format_state(self, state: DownloadState) -> str:
        if state == DownloadState.DOWNLOADING:
            return f"{CLR_GREEN}> DOWNLOADING{CLR_RESET}"
        if state == DownloadState.COMPLETED:
            return f"{CLR_PURPLE}* COMPLETED  {CLR_RESET}"
        if state == DownloadState.PAUSED:
            return f"{CLR_YELLOW}|| PAUSED    {CLR_RESET}"
        if state == DownloadState.FAILED:
            return f"{CLR_RED}x FAILED     {CLR_RESET}"
        if state == DownloadState.STARTING:
            return f"{CLR_GRAY}o STARTING   {CLR_RESET}"
        return f"{CLR_GRAY}? {state.value.upper():<10}{CLR_RESET}"
