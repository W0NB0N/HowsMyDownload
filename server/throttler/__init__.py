"""Throttling module for rate-limiting push notifications."""

from server.throttler.push_throttler import PushThrottler

__all__ = ["PushThrottler"]
