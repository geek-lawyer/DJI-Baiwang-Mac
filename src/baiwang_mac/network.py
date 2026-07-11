from __future__ import annotations

import re
import subprocess
import json
from dataclasses import dataclass


@dataclass(slots=True)
class NetworkStatus:
    wifi_power: bool
    wifi_active: bool
    baiwang_active: bool
    baiwang_ip: str
    default_interface: str
    interface: str = ""
    public_ip: str = "--"
    public_country: str = ""
    public_city: str = ""
    latency_ms: float | None = None
    usb_power_ma: int | None = None


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

    def baiwang_interface(self) -> str:
        output = self._run(["networksetup", "-listallhardwareports"])
        blocks = output.split("\n\n")
        for block in blocks:
            if re.search(r"Hardware Port:\s*Baiwang\s*$", block, re.M | re.I):
                match = re.search(r"Device:\s*(\S+)", block)
                if match:
                    return match.group(1)
        return "en6"

    def status(self) -> NetworkStatus:
        baiwang_interface = self.baiwang_interface()
        wifi = self._run(["networksetup", "-getairportpower", "en0"])
        interfaces = self._run(["ifconfig", "-a"])
        default = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True).stdout

        def block(name: str) -> str:
            match = re.search(rf"^{re.escape(name)}:.*?(?=^[a-z0-9]+:|\Z)", interfaces, re.M | re.S)
            return match.group(0) if match else ""

        en0 = block("en0")
        baiwang = block(baiwang_interface)
        ip = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", baiwang)
        route_interface = re.search(r"interface:\s*(\S+)", default)
        return NetworkStatus(
            wifi_power="On" in wifi,
            wifi_active="status: active" in en0,
            baiwang_active="status: active" in baiwang,
            baiwang_ip=ip.group(1) if ip else "--",
            default_interface=route_interface.group(1) if route_interface else "--",
            interface=baiwang_interface,
        )

    def latency(self, interface: str | None = None) -> float | None:
        interface = interface or self.baiwang_interface()
        result = subprocess.run(
            ["ping", "-b", interface, "-c", "1", "-W", "1000", "1.1.1.1"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        match = re.search(r"time[=<]([0-9.]+)\s*ms", result.stdout)
        return float(match.group(1)) if match else None

    def public_exit(self, interface: str | None = None) -> tuple[str, str, str]:
        """Return the exit IP and inferred location using an external lookup.

        The first request is bound to the dongle interface so a VPN or Wi-Fi
        default route does not accidentally report the wrong egress address.
        """
        interface = interface or self.baiwang_interface()
        ip = self._run(
            ["curl", "--interface", interface, "--max-time", "8", "-fsS", "https://api.ipify.org"],
            timeout=10,
        ).strip()
        if not re.fullmatch(r"[0-9A-Fa-f:.]+", ip):
            raise RuntimeError("公网出口 IP 返回格式不正确")
        raw = self._run(["curl", "--max-time", "8", "-fsS", f"https://ipwho.is/{ip}"], timeout=10)
        data = json.loads(raw)
        if not data.get("success", True):
            return ip, "", ""
        return ip, str(data.get("country", "")), str(data.get("city", ""))

    def speed_test(self, interface: str | None = None) -> dict[str, float | str]:
        interface = interface or self.baiwang_interface()
        output = self._run(["networkQuality", "-I", interface, "-s", "-M", "20"], timeout=30)
        down = re.search(r"Downlink capacity:\s*([0-9.]+)\s*(\S+)", output, re.I)
        up = re.search(r"Uplink capacity:\s*([0-9.]+)\s*(\S+)", output, re.I)
        responsiveness = re.search(r"Responsiveness:\s*([0-9.]+)\s*(\S+)", output, re.I)
        return {
            "download": float(down.group(1)) if down else 0.0,
            "download_unit": down.group(2) if down else "Mbps",
            "upload": float(up.group(1)) if up else 0.0,
            "upload_unit": up.group(2) if up else "Mbps",
            "responsiveness": float(responsiveness.group(1)) if responsiveness else 0.0,
            "raw": output,
        }

    def usb_power_allocation(self) -> int | None:
        output = self._run(["ioreg", "-p", "IOUSB", "-w0", "-l"])
        match = re.search(
            r"Baiwang@.*?\"UsbPowerSinkAllocation\"\s*=\s*(\d+)",
            output,
            re.I | re.S,
        )
        return int(match.group(1)) if match else None

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
