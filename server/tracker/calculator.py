"""Speed smoothing, ETA, and progress percentage computation utilities."""

from collections import deque


def calculate_percentage(bytes_downloaded: int, total_bytes: int | None) -> float | None:
    """Computes progress percentage (0.0 - 100.0) or None if total size is unknown."""
    if total_bytes is None or total_bytes <= 0:
        return None
    if bytes_downloaded >= total_bytes:
        return 100.0
    return round((bytes_downloaded / total_bytes) * 100.0, 1)


def calculate_eta(
    bytes_downloaded: int,
    total_bytes: int | None,
    smoothed_speed: int
) -> int | None:
    """Computes estimated seconds remaining (ETA) or None if indeterminate."""
    if total_bytes is None or total_bytes <= 0:
        return None
    if bytes_downloaded >= total_bytes:
        return 0
    if smoothed_speed <= 0:
        return None

    remaining_bytes = total_bytes - bytes_downloaded
    return max(0, int(remaining_bytes / smoothed_speed))


class SpeedSmoother:
    """Maintains recent sample history and computes Exponential Moving Average (EMA) speed."""

    def __init__(self, window_size: int = 5, ema_alpha: float = 0.35) -> None:
        self.window_size = window_size
        self.ema_alpha = ema_alpha
        self.history: deque[tuple[float, int]] = deque(maxlen=window_size)  # (timestamp_sec, bytes)
        self.current_smoothed_speed: float = 0.0

    def update(self, timestamp: float, bytes_downloaded: int) -> int:
        """Adds a sample and returns the current smoothed speed in bytes/sec."""
        if not self.history:
            self.history.append((timestamp, bytes_downloaded))
            return int(self.current_smoothed_speed)

        last_time, last_bytes = self.history[-1]
        dt = timestamp - last_time

        # If sample arrives too quickly (< 0.1s), avoid division instability
        if dt < 0.1:
            return int(self.current_smoothed_speed)

        delta_bytes = bytes_downloaded - last_bytes
        self.history.append((timestamp, bytes_downloaded))

        # Edge Case 1: Download restarted or shrunk
        if delta_bytes < 0:
            self.current_smoothed_speed = 0.0
            return 0

        # Edge Case 2: Stalled (no bytes in a long interval)
        if delta_bytes == 0:
            # Decay speed by 50% for each stalled interval
            self.current_smoothed_speed *= 0.5
            if self.current_smoothed_speed < 1024:  # Under 1 KB/s -> snap to 0
                self.current_smoothed_speed = 0.0
            return int(self.current_smoothed_speed)

        instant_speed = delta_bytes / dt

        # Apply Exponential Moving Average (EMA)
        if self.current_smoothed_speed == 0.0:
            self.current_smoothed_speed = instant_speed
        else:
            self.current_smoothed_speed = (
                self.ema_alpha * instant_speed
                + (1.0 - self.ema_alpha) * self.current_smoothed_speed
            )

        return max(0, int(round(self.current_smoothed_speed)))

    def reset(self) -> None:
        """Resets sample history."""
        self.history.clear()
        self.current_smoothed_speed = 0.0
