from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class NetworkStatus:
    wifi_power: bool
    wifi_active: bool
    baiwang_active: bool
    baiwang_ip: str
    default_interface: str


class NetworkManager:
    @staticmethod
    def _run(args: list[str], timeout: int = 20) -> str:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result.stdout

    def services(self) -> list[str]:
        output = self._run(["networksetup", "-listallnetworkservices"])
        return [line.lstrip("*").strip() for line in output.splitlines()[1:] if line.strip()]

    def status(self) -> NetworkStatus:
        wifi = self._run(["networksetup", "-getairportpower", "en0"])
        interfaces = self._run(["ifconfig", "-a"])
        default = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True).stdout

        def block(name: str) -> str:
            match = re.search(rf"^{re.escape(name)}:.*?(?=^[a-z0-9]+:|\Z)", interfaces, re.M | re.S)
            return match.group(0) if match else ""

        en0 = block("en0")
        en6 = block("en6")
        ip = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", en6)
        route_interface = re.search(r"interface:\s*(\S+)", default)
        return NetworkStatus(
            wifi_power="On" in wifi,
            wifi_active="status: active" in en0,
            baiwang_active="status: active" in en6,
            baiwang_ip=ip.group(1) if ip else "--",
            default_interface=route_interface.group(1) if route_interface else "--",
        )

    def _set_service_order(self, preferred: str) -> None:
        services = self.services()
        if preferred not in services:
            raise RuntimeError(f"找不到网络服务：{preferred}")
        ordered = [preferred] + [item for item in services if item != preferred]
        self._run(["networksetup", "-ordernetworkservices", *ordered])

    def switch(self, mode: str) -> None:
        if mode == "wifi":
            self._run(["networksetup", "-setairportpower", "en0", "on"])
            self._set_service_order("Wi-Fi")
        elif mode == "4g":
            self._run(["networksetup", "-setnetworkserviceenabled", "Baiwang", "on"])
            self._run(["networksetup", "-setairportpower", "en0", "off"])
        elif mode == "auto":
            self._run(["networksetup", "-setnetworkserviceenabled", "Baiwang", "on"])
            self._run(["networksetup", "-setairportpower", "en0", "on"])
            self._set_service_order("Baiwang")
        else:
            raise RuntimeError("未知的网络切换模式")

