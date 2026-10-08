"""Unit tests for speed smoothing, ETA, and percentage calculations."""

from server.tracker.calculator import SpeedSmoother, calculate_eta, calculate_percentage


def test_calculate_percentage():
    # Normal case
    assert calculate_percentage(500, 1000) == 50.0
    assert calculate_percentage(333, 1000) == 33.3

    # Boundary cases
    assert calculate_percentage(0, 1000) == 0.0
    assert calculate_percentage(1000, 1000) == 100.0
    assert calculate_percentage(1200, 1000) == 100.0

    # Indeterminate / unknown total
    assert calculate_percentage(500, None) is None
    assert calculate_percentage(500, 0) is None
    assert calculate_percentage(500, -100) is None


def test_calculate_eta():
    # Normal case: 50MB remaining @ 10MB/s -> 5s
    assert calculate_eta(50_000_000, 100_000_000, 10_000_000) == 5

    # Speed is 0 or negative
    assert calculate_eta(50_000_000, 100_000_000, 0) is None
    assert calculate_eta(50_000_000, 100_000_000, -1000) is None

    # Total unknown
    assert calculate_eta(50_000_000, None, 10_000_000) is None

    # Completed
    assert calculate_eta(100_000_000, 100_000_000, 10_000_000) == 0


def test_speed_smoother_progression():
    smoother = SpeedSmoother(window_size=5, ema_alpha=0.5)

    # Initial sample at t=0
    s0 = smoother.update(timestamp=0.0, bytes_downloaded=0)
    assert s0 == 0

    # 10MB received in 2.0s -> instantaneous 5MB/s
    s1 = smoother.update(timestamp=2.0, bytes_downloaded=10_000_000)
    assert s1 == 5_000_000

    # Next 10MB in 2.0s (total 20MB @ t=4.0) -> instant 5MB/s -> EMA stays 5MB/s
    s2 = smoother.update(timestamp=4.0, bytes_downloaded=20_000_000)
    assert s2 == 5_000_000

    # Speed spike: 20MB in 2.0s (total 40MB @ t=6.0) -> instant 10MB/s
    # EMA: 0.5 * 10M + 0.5 * 5M = 7.5MB/s
    s3 = smoother.update(timestamp=6.0, bytes_downloaded=40_000_000)
    assert s3 == 7_500_000


def test_speed_smoother_edge_cases():
    smoother = SpeedSmoother()

    # Initial points
    smoother.update(timestamp=0.0, bytes_downloaded=0)
    smoother.update(timestamp=2.0, bytes_downloaded=10_000_000)

    # Edge Case 1: Negative delta (download restart)
    s_restart = smoother.update(timestamp=4.0, bytes_downloaded=1_000_000)
    assert s_restart == 0

    # Edge Case 2: Stalled interval (0 delta)
    smoother.update(timestamp=6.0, bytes_downloaded=10_000_000)
    s_stall1 = smoother.update(timestamp=8.0, bytes_downloaded=10_000_000)
    # Speed decayed
    assert s_stall1 < 5_000_000
