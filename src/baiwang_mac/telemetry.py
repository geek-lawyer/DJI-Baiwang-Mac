from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psutil


@dataclass(slots=True)
class TrafficSnapshot:
    interface: str
    connected: bool
    session_seconds: int
    session_received: int
    session_sent: int
    cycle_received: int
    cycle_sent: int
    down_bytes_per_second: float
    up_bytes_per_second: float
    average_down_bytes_per_second: float
    average_up_bytes_per_second: float

    @property
    def session_total(self) -> int:
        return self.session_received + self.session_sent

    @property
    def cycle_total(self) -> int:
        return self.cycle_received + self.cycle_sent


def cycle_id(today: date, reset_day: int) -> str:
    reset_day = max(1, min(28, int(reset_day)))
    if today.day >= reset_day:
        return f"{today.year:04d}-{today.month:02d}-{reset_day:02d}"
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}-{reset_day:02d}"


def format_bytes(value: float, decimals: int = 2) -> str:
    value = max(0.0, float(value))
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    digits = 0 if index == 0 else decimals
    return f"{value:.{digits}f} {units[index]}"


def format_speed_pair(down_bps: float, up_bps: float, family: str = "bytes") -> tuple[str, str]:
    """Format both directions with one shared unit scale.

    The faster direction chooses the scale so download and upload never mix
    MB/s with KB/s (or Mbps with Kbps) in the same view.
    """
    down = max(0.0, float(down_bps))
    up = max(0.0, float(up_bps))
    if family == "bits":
        down *= 8
        up *= 8
        base_units = ("bps", "Kbps", "Mbps", "Gbps")
        divisor = 1000.0
    else:
        base_units = ("B/s", "KB/s", "MB/s", "GB/s")
        divisor = 1024.0
    largest = max(down, up)
    unit_index = 0
    while largest >= divisor and unit_index < len(base_units) - 1:
        largest /= divisor
        down /= divisor
        up /= divisor
        unit_index += 1
    digits = 0 if unit_index == 0 else 2
    unit = base_units[unit_index]
    return f"{down:.{digits}f} {unit}", f"{up:.{digits}f} {unit}"


class TrafficMonitor:
    def __init__(self, interface: str, state_path: Path, reset_day: int = 1):
        self.interface = interface
        self.state_path = state_path
        self.reset_day = max(1, min(28, int(reset_day)))
        self.state = self._load_state()
        self._last_time = time.monotonic()
        self._last_received: int | None = None
        self._last_sent: int | None = None
        self._session_started: float | None = None
        self._session_received = 0
        self._session_sent = 0
        self._last_active = False

    def _load_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_reset_day(self, reset_day: int):
        self.reset_day = max(1, min(28, int(reset_day)))

    def sample(self, active: bool) -> TrafficSnapshot:
        counters = psutil.net_io_counters(pernic=True).get(self.interface)
        now = time.monotonic()
        elapsed = max(0.001, now - self._last_time)
        received = int(counters.bytes_recv) if counters else 0
        sent = int(counters.bytes_sent) if counters else 0

        current_cycle = cycle_id(date.today(), self.reset_day)
        if self.state.get("cycle_id") != current_cycle:
            self.state = {"cycle_id": current_cycle, "received": 0, "sent": 0}

        down_rate = up_rate = 0.0
        if active and not self._last_active:
            self._session_started = now
            self._session_received = 0
            self._session_sent = 0
            self._last_received = received
            self._last_sent = sent
        elif active and self._last_received is not None and self._last_sent is not None:
            received_delta = received - self._last_received
            sent_delta = sent - self._last_sent
            # Interface counters reset when the module is unplugged. Never turn
            # a reset into a negative or impossibly large usage adjustment.
            received_delta = received_delta if 0 <= received_delta <= 10 * 1024**3 else 0
            sent_delta = sent_delta if 0 <= sent_delta <= 10 * 1024**3 else 0
            self._session_received += received_delta
            self._session_sent += sent_delta
            self.state["received"] = int(self.state.get("received", 0)) + received_delta
            self.state["sent"] = int(self.state.get("sent", 0)) + sent_delta
            down_rate = received_delta / elapsed
            up_rate = sent_delta / elapsed
            self._save_state()

        if not active:
            self._session_started = None
        self._last_received = received
        self._last_sent = sent
        self._last_time = now
        self._last_active = active
        session_seconds = int(now - self._session_started) if self._session_started else 0
        average_down = self._session_received / session_seconds if session_seconds else 0.0
        average_up = self._session_sent / session_seconds if session_seconds else 0.0
        return TrafficSnapshot(
            interface=self.interface,
            connected=active,
            session_seconds=session_seconds,
            session_received=self._session_received,
            session_sent=self._session_sent,
            cycle_received=int(self.state.get("received", 0)),
            cycle_sent=int(self.state.get("sent", 0)),
            down_bytes_per_second=down_rate,
            up_bytes_per_second=up_rate,
            average_down_bytes_per_second=average_down,
            average_up_bytes_per_second=average_up,
        )
