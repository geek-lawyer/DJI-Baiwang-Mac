from __future__ import annotations

import ctypes.util
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import usb.backend.libusb1
import usb.core
import usb.util


VID = 0x2CA3
PID = 0x4006


class BaiwangError(RuntimeError):
    pass


@dataclass(slots=True)
class DeviceStatus:
    connected: bool = False
    sim_ready: bool = False
    carrier: str = "--"
    signal_csq: int = 99
    signal_dbm: int | None = None
    signal_percent: int = 0
    registered: bool = False
    ims_enabled: bool = False
    sms_domain: int | None = None
    network: str = "--"
    band: str = "--"
    channel: str = "--"
    ip_address: str = "--"
    at_interface: int | None = None
    temperatures: tuple[int, ...] = ()
    max_temperature: int | None = None


@dataclass(slots=True)
class SMSMessage:
    index: int
    status: str
    sender: str
    timestamp: str
    body: str


@dataclass(slots=True)
class ProvisioningInfo:
    usbnet_mode: int | None
    carrier: str
    selected_mbn: str
    available_mbns: tuple[str, ...]
    target_mbn: str | None
    ims_enabled: bool
    sms_domain: int | None
    needs_initialization: bool
    reasons: tuple[str, ...]


def _resource_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root.joinpath(*parts)


def find_libusb(_name: str) -> str | None:
    candidates = [
        os.environ.get("LIBUSB_PATH"),
        str(_resource_path("lib", "libusb-1.0.dylib")),
        "/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib",
        "/usr/local/opt/libusb/lib/libusb-1.0.dylib",
        ctypes.util.find_library("usb-1.0"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def decode_ucs2(value: str) -> str:
    value = value.strip()
    if value and len(value) % 4 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", value):
        try:
            return bytes.fromhex(value).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            pass
    return value


def encode_ucs2(value: str) -> str:
    return value.encode("utf-16-be").hex().upper()


def normalize_phone(value: str) -> str:
    value = re.sub(r"[\s()-]", "", value)
    if not re.fullmatch(r"\+?\d{5,20}", value):
        raise BaiwangError("电话号码格式不正确")
    return value


def format_sms_timestamp(value: str) -> str:
    match = re.match(r"(\d{2})/(\d{2})/(\d{2}),(\d{2}:\d{2}:\d{2})(?:[+-]\d+)?", value)
    if not match:
        return value
    year, month, day, clock = match.groups()
    century = "19" if int(year) >= 70 else "20"
    return f"{century}{year}-{month}-{day} {clock}"


class ATSession:
    def __init__(self):
        backend = usb.backend.libusb1.get_backend(find_library=find_libusb)
        if backend is None:
            raise BaiwangError("找不到 libusb")
        self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        if self.dev is None:
            raise BaiwangError("未找到 DJI Baiwang 模块")
        self.out_ep, self.in_ep, self.interface = self._find_at_endpoint()
        self._drain()

    def _find_at_endpoint(self):
        for cfg in self.dev:
            for intf in cfg:
                if intf.bInterfaceClass != 0xFF:
                    continue
                outs = [
                    ep for ep in intf
                    if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
                    and usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                ]
                ins = [
                    ep for ep in intf
                    if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                    and usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                ]
                if not outs or not ins:
                    continue
                try:
                    outs[0].write(b"AT\r", timeout=700)
                    deadline = time.monotonic() + 1.2
                    chunks: list[bytes] = []
                    while time.monotonic() < deadline:
                        try:
                            chunks.append(bytes(ins[0].read(1024, timeout=250)))
                            if b"OK" in b"".join(chunks):
                                break
                        except usb.core.USBTimeoutError:
                            continue
                    response = b"".join(chunks).decode(errors="ignore")
                    if "OK" in response:
                        return outs[0], ins[0], intf.bInterfaceNumber
                except usb.core.USBError:
                    continue
        raise BaiwangError("模块已连接，但 AT 控制端口暂时没有响应")

    def _drain(self) -> str:
        """Consume stale command echoes and asynchronous URCs before a request."""
        chunks: list[bytes] = []
        while True:
            try:
                chunks.append(bytes(self.in_ep.read(4096, timeout=80)))
            except usb.core.USBError:
                break
        return b"".join(chunks).decode("utf-8", errors="ignore")

    def command(self, command: str, timeout: float = 6, expect_prompt: bool = False) -> str:
        self._drain()
        self.out_ep.write((command + "\r").encode("ascii"), timeout=1200)
        chunks: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = bytes(self.in_ep.read(4096, timeout=500)).decode("utf-8", errors="ignore")
                chunks.append(chunk)
                response = "".join(chunks)
                if expect_prompt and ">" in response:
                    return response
                if re.search(
                    r"(?:^|\r?\n)(?:OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)(?:\r?\n|$)",
                    response,
                ):
                    return response
            except usb.core.USBTimeoutError:
                continue
        response = "".join(chunks)
        if response:
            return response
        raise BaiwangError(f"指令超时：{command}")

    def write_sms_payload(self, payload: str, timeout: float = 60) -> str:
        self.out_ep.write(payload.encode("ascii") + b"\x1a", timeout=2000)
        chunks: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = bytes(self.in_ep.read(4096, timeout=1000)).decode("utf-8", errors="ignore")
                chunks.append(chunk)
                response = "".join(chunks)
                if re.search(r"(?:OK|ERROR|\+CMS ERROR:.*)(?:\r?\n|$)", response):
                    return response
            except usb.core.USBTimeoutError:
                continue
        return "".join(chunks)

    def close(self) -> None:
        dev = getattr(self, "dev", None)
        if dev is not None:
            try:
                usb.util.dispose_resources(dev)
            except usb.core.USBError:
                pass
            self.dev = None

    def __del__(self):
        self.close()


class BaiwangController:
    def __init__(self):
        self._lock = threading.RLock()
        self._at_session: ATSession | None = None

    def _session(self, attempts: int = 5) -> ATSession:
        if self._at_session is not None:
            try:
                if "OK" in self._at_session.command("AT", timeout=2):
                    return self._at_session
            except (BaiwangError, usb.core.USBError, AttributeError):
                pass
            self._at_session.close()
            self._at_session = None
        error: Exception | None = None
        for attempt in range(attempts):
            try:
                self._at_session = ATSession()
                return self._at_session
            except (BaiwangError, usb.core.USBError) as exc:
                error = exc
                if attempt + 1 < attempts:
                    time.sleep(2)
        raise BaiwangError(str(error or "无法连接模块"))

    @staticmethod
    def _value(response: str, prefix: str) -> str:
        for line in response.replace("\r", "").splitlines():
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return ""

    def get_status(self) -> DeviceStatus:
        with self._lock:
            at = self._session()
            status = DeviceStatus(connected=True, at_interface=at.interface)
            cpin = at.command("AT+CPIN?")
            status.sim_ready = "READY" in cpin
            csq = self._value(at.command("AT+CSQ"), "+CSQ:")
            match = re.search(r"(\d+)", csq)
            if match:
                status.signal_csq = int(match.group(1))
                if 0 <= status.signal_csq <= 31:
                    status.signal_dbm = -113 + (2 * status.signal_csq)
                    status.signal_percent = round(status.signal_csq / 31 * 100)
            cops = self._value(at.command("AT+COPS?"), "+COPS:")
            carrier = re.search(r'"([^"]+)"', cops)
            if carrier:
                status.carrier = carrier.group(1)
            cereg = self._value(at.command("AT+CEREG?"), "+CEREG:")
            status.registered = bool(re.search(r",(?:1|5)(?:,|$)", cereg))
            ims = self._value(at.command('AT+QCFG="ims"'), "+QCFG:")
            status.ims_enabled = bool(re.search(r'"ims",1,1', ims))
            cgsms = self._value(at.command("AT+CGSMS?"), "+CGSMS:")
            if cgsms.isdigit():
                status.sms_domain = int(cgsms)
            qnw = self._value(at.command("AT+QNWINFO"), "+QNWINFO:")
            fields = re.findall(r'"([^"]*)"|,(\d+)', qnw)
            quoted = re.findall(r'"([^"]*)"', qnw)
            if quoted:
                status.network = quoted[0]
            if len(quoted) >= 3:
                status.band = quoted[2]
            channel = re.search(r",(\d+)\s*$", qnw)
            if channel:
                status.channel = channel.group(1)
            cgpaddr = self._value(at.command("AT+CGPADDR=1"), "+CGPADDR:")
            ip = re.search(r'"([^",]+)', cgpaddr)
            if ip:
                status.ip_address = ip.group(1)
            temp_response = at.command("AT+QTEMP")
            temperatures: list[int] = []
            for line in temp_response.replace("\r", "").splitlines():
                if not line.startswith("+QTEMP:"):
                    continue
                payload = line.split(":", 1)[1]
                quoted_values = [int(item) for item in re.findall(r'"(-?\d+)"', payload)]
                values = quoted_values or [int(item) for item in re.findall(r"-?\d+", payload)]
                temperatures.extend(value for value in values if -50 <= value <= 150)
            status.temperatures = tuple(temperatures)
            status.max_temperature = max(temperatures) if temperatures else None
            return status

    @staticmethod
    def _operator_profile(carrier: str, available: Iterable[str]) -> str | None:
        carrier_upper = carrier.upper()
        candidates: list[str] = []
        if any(token in carrier_upper for token in ("CHN-CT", "CHINA TELECOM", "CTCC", "46011", "46003")):
            candidates = ["VoLTE_OPNMKT_CT"]
        elif any(token in carrier_upper for token in ("CHINA MOBILE", "CMCC", "46000", "46002", "46007")):
            candidates = ["Volte_OpenMkt-Commercial-CMCC"]
        elif any(token in carrier_upper for token in ("CHN-CU", "CHINA UNICOM", "UNICOM", "46001", "46006")):
            candidates = ["CU-VoLTE"]
        available_set = set(available)
        return next((item for item in candidates if item in available_set), None)

    def inspect_provisioning(self) -> ProvisioningInfo:
        with self._lock:
            at = self._session()
            usbnet_response = at.command('AT+QCFG="usbnet"')
            usbnet_match = re.search(r'"usbnet",(\d+)', usbnet_response)
            usbnet_mode = int(usbnet_match.group(1)) if usbnet_match else None

            cops = self._value(at.command("AT+COPS?"), "+COPS:")
            carrier_match = re.search(r'"([^"]+)"', cops)
            carrier = carrier_match.group(1) if carrier_match else "未知运营商"

            ims = self._value(at.command('AT+QCFG="ims"'), "+QCFG:")
            ims_enabled = bool(re.search(r'"ims",1,1', ims))
            sms_value = self._value(at.command("AT+CGSMS?"), "+CGSMS:")
            sms_domain = int(sms_value) if sms_value.isdigit() else None

            mbn_response = at.command('AT+QMBNCFG="List"', timeout=35)
            available_mbns = tuple(re.findall(r'"List",\d+,\d+,\d+,"([^"]+)"', mbn_response))
            selected_mbn = ""
            for line in mbn_response.replace("\r", "").splitlines():
                match = re.search(r'"List",\d+,1,1,"([^"]+)"', line)
                if match:
                    selected_mbn = match.group(1)
                    break
            target_mbn = self._operator_profile(carrier, available_mbns)

            reasons: list[str] = []
            if usbnet_mode != 1:
                reasons.append("USB 尚未切换为 macOS 原生 CDC-ECM 网卡模式")
            if target_mbn and selected_mbn != target_mbn:
                reasons.append(f"当前运营商配置为 {selected_mbn or '未选择'}，建议使用 {target_mbn}")
            if target_mbn and not ims_enabled:
                reasons.append("IMS/VoLTE 尚未开启")
            if target_mbn and sms_domain != 2:
                reasons.append("LTE 短信尚未设置为分组域优先")
            return ProvisioningInfo(
                usbnet_mode=usbnet_mode,
                carrier=carrier,
                selected_mbn=selected_mbn,
                available_mbns=available_mbns,
                target_mbn=target_mbn,
                ims_enabled=ims_enabled,
                sms_domain=sms_domain,
                needs_initialization=bool(reasons),
                reasons=tuple(reasons),
            )

    def initialize_module(
        self,
        info: ProvisioningInfo | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> ProvisioningInfo:
        def report(message: str) -> None:
            if progress:
                progress(message)

        with self._lock:
            info = info or self.inspect_provisioning()
            if not info.needs_initialization:
                return info
            at = self._session()
            changed = False

            if info.target_mbn and info.selected_mbn != info.target_mbn:
                report(f"切换运营商配置：{info.target_mbn}")
                commands = [
                    'AT+QMBNCFG="Deactivate"',
                    'AT+QMBNCFG="AutoSel",0',
                    f'AT+QMBNCFG="Select","{info.target_mbn}"',
                ]
                for command in commands:
                    response = at.command(command, timeout=15)
                    if "OK" not in response:
                        raise BaiwangError(f"运营商配置失败：{response.strip()}")
                changed = True

            if info.target_mbn and not info.ims_enabled:
                report("开启 IMS/VoLTE")
                response = at.command('AT+QCFG="ims",1')
                if "OK" not in response:
                    raise BaiwangError(f"开启 IMS 失败：{response.strip()}")
                changed = True

            if info.target_mbn and info.sms_domain != 2:
                report("设置 LTE 短信分组域")
                response = at.command("AT+CGSMS=2")
                if "OK" not in response:
                    raise BaiwangError(f"设置短信通道失败：{response.strip()}")
                changed = True

            if info.usbnet_mode != 1:
                report("切换 USB 为 CDC-ECM 网卡模式")
                response = at.command('AT+QCFG="usbnet",1')
                if "OK" not in response:
                    raise BaiwangError(f"切换 ECM 失败：{response.strip()}")
                changed = True

            if changed:
                report("重启模块并等待重新连接")
                try:
                    at.command("AT+CFUN=1,1", timeout=6)
                except (BaiwangError, usb.core.USBError):
                    # USB disconnect during reboot is expected.
                    pass
            return info

    def send_sms(self, number: str, body: str) -> int | None:
        number = normalize_phone(number)
        if not body:
            raise BaiwangError("短信内容不能为空")
        if len(body) > 335:
            raise BaiwangError("短信过长，请控制在 335 个字符以内")
        with self._lock:
            at = self._session()
            for command in ('AT+CMGF=1', 'AT+CSCS="UCS2"', "AT+CSMP=17,167,0,8"):
                response = at.command(command)
                if "OK" not in response:
                    raise BaiwangError(f"模块拒绝短信编码配置：{response.strip()}")
            prompt = at.command(f'AT+CMGS="{encode_ucs2(number)}"', timeout=10, expect_prompt=True)
            if ">" not in prompt:
                raise BaiwangError("模块没有进入短信发送状态")
            response = at.write_sms_payload(encode_ucs2(body))
            if "+CMS ERROR:" in response:
                code = re.search(r"\+CMS ERROR:\s*(\d+)", response)
                hint = "；请检查 IMS、运营商 MBN 和 SIM 短信权限" if code and code.group(1) == "350" else ""
                raise BaiwangError(f"运营商拒绝发送 {code.group(0) if code else ''}{hint}")
            if "+CMGS:" not in response or "OK" not in response:
                raise BaiwangError("短信发送失败，模块未返回成功确认")
            reference = re.search(r"\+CMGS:\s*(\d+)", response)
            return int(reference.group(1)) if reference else None

    @staticmethod
    def _parse_messages(response: str) -> list[SMSMessage]:
        lines = [line.strip() for line in response.replace("\r", "").splitlines()]
        messages: list[SMSMessage] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.startswith("+CMGL:"):
                index += 1
                continue
            head = line[len("+CMGL:"):].strip()
            parts = next(iter(re.findall(r'(?:[^,"]|"[^"]*")+', head)), "")
            fields = [item.strip().strip('"') for item in re.findall(r'(?:[^,"]+|"[^"]*")+', head)]
            body = lines[index + 1] if index + 1 < len(lines) else ""
            try:
                msg_index = int(fields[0])
            except (ValueError, IndexError):
                index += 1
                continue
            decoded = [decode_ucs2(field) for field in fields]
            messages.append(
                SMSMessage(
                    index=msg_index,
                    status=decoded[1] if len(decoded) > 1 else "",
                    sender=decoded[2] if len(decoded) > 2 else "",
                    timestamp=format_sms_timestamp(decoded[3]) if len(decoded) > 3 else "",
                    body=decode_ucs2(body),
                )
            )
            index += 2
        return messages

    def list_messages(self, unread_only: bool = False) -> list[SMSMessage]:
        with self._lock:
            at = self._session()
            for command in ('AT+CMGF=1', 'AT+CSCS="UCS2"', 'AT+CPMS="ME","ME","ME"'):
                response = at.command(command)
                if "OK" not in response:
                    raise BaiwangError(f"读取短信准备失败：{response.strip()}")
            mode = "REC UNREAD" if unread_only else "ALL"
            response = at.command(f'AT+CMGL="{mode}"', timeout=20)
            if "+CMS ERROR:" in response:
                raise BaiwangError(response.strip())
            return self._parse_messages(response)

    def delete_sms(self, index: int) -> None:
        with self._lock:
            at = self._session()
            storage = at.command('AT+CPMS="ME","ME","ME"')
            if "OK" not in storage:
                raise BaiwangError(f"选择短信存储失败：{storage.strip()}")
            response = at.command(f"AT+CMGD={int(index)}", timeout=10)
            if "OK" not in response:
                raise BaiwangError(f"删除失败：{response.strip()}")

    def set_radio_mode(self, mode: str) -> None:
        modes = {"auto": 0, "lte": 3}
        if mode not in modes:
            raise BaiwangError("不支持的网络模式")
        with self._lock:
            response = self._session().command(f'AT+QCFG="nwscanmode",{modes[mode]},1')
            if "OK" not in response:
                raise BaiwangError("当前固件不支持修改网络制式")


def is_baiwang_present() -> bool:
    backend = usb.backend.libusb1.get_backend(find_library=find_libusb)
    return bool(backend and usb.core.find(idVendor=VID, idProduct=PID, backend=backend))
