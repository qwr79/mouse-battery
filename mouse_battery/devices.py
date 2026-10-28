"""Battery readers for 2.4 GHz mice and Bluetooth devices on Windows."""

from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Optional

from . import hid

setupapi = hid.setupapi
kernel32 = hid.kernel32

DIGCF_PRESENT = 0x02
DIGCF_ALLCLASSES = 0x04
SPDRP_DEVICEDESC = 0x00
SPDRP_FRIENDLYNAME = 0x0C
CLASS_BLUETOOTH = hid.GUID(
    0xE0CBF06C,
    0xCD8B,
    0x4647,
    (ctypes.c_ubyte * 8)(0xBB, 0x8A, 0x26, 0x3B, 0x43, 0xF0, 0xF9, 0x74),
)
CLASS_SYSTEM = hid.GUID(
    0x4D36E97D,
    0xE325,
    0x11CE,
    (ctypes.c_ubyte * 8)(0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18),
)
BLUETOOTH_PROPERTY = hid.GUID(
    0x104EA319,
    0x6EE2,
    0x4701,
    (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5),
)

ATK_VIDS = {0x373B, 0x3554}


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", hid.GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", hid.GUID), ("pid", wintypes.DWORD)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", wintypes.WORD),
        ("wMonth", wintypes.WORD),
        ("wDayOfWeek", wintypes.WORD),
        ("wDay", wintypes.WORD),
        ("wHour", wintypes.WORD),
        ("wMinute", wintypes.WORD),
        ("wSecond", wintypes.WORD),
        ("wMilliseconds", wintypes.WORD),
    ]


class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong), ("rgBytes", ctypes.c_ubyte * 6)]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Address", BLUETOOTH_ADDRESS),
        ("ulClassofDevice", wintypes.ULONG),
        ("fConnected", wintypes.BOOL),
        ("fRemembered", wintypes.BOOL),
        ("fAuthenticated", wintypes.BOOL),
        ("stLastSeen", SYSTEMTIME),
        ("stLastUsed", SYSTEMTIME),
        ("szName", wintypes.WCHAR * 248),
    ]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("fReturnAuthenticated", wintypes.BOOL),
        ("fReturnRemembered", wintypes.BOOL),
        ("fReturnUnknown", wintypes.BOOL),
        ("fReturnConnected", wintypes.BOOL),
        ("fIssueInquiry", wintypes.BOOL),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", ctypes.c_void_p),
    ]


_bthprops = ctypes.WinDLL("bthprops.cpl", use_last_error=True)
_bthprops.BluetoothFindFirstDevice.restype = ctypes.c_void_p
_bthprops.BluetoothFindFirstDevice.argtypes = [
    ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS),
    ctypes.POINTER(BLUETOOTH_DEVICE_INFO),
]
_bthprops.BluetoothFindNextDevice.restype = wintypes.BOOL
_bthprops.BluetoothFindNextDevice.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(BLUETOOTH_DEVICE_INFO),
]
_bthprops.BluetoothFindDeviceClose.argtypes = [ctypes.c_void_p]


setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInfo.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVINFO_DATA),
]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    ctypes.POINTER(PROPERTYKEY),
    ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    wintypes.LPWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]


@dataclass
class Device:
    key: str
    name: str
    transport: str
    subtitle: str
    level: int
    source: str
    voltage_mv: int | None = None
    address: str = ""
    charging: Optional[bool] = None

    @property
    def is_mouse(self) -> bool:
        low = self.name.lower()
        return self.transport == "2.4G" or "mouse" in low or "鼠标" in self.name


@dataclass
class Snapshot:
    devices: list[Device]
    timestamp: float
    mouse_error: str = ""
    bluetooth_error: str = ""

    @property
    def count(self) -> int:
        return len(self.devices)


# ---------------------------------------------------------------------------
# 2.4 GHz ATK / VXE / NK mouse
# ---------------------------------------------------------------------------
def _clean_mouse_name(product: str) -> str:
    name = product.strip()
    name = re.sub(
        r"\s+(?:nano\s+)?(?:2\.4g\s+)?(?:usb\s+)?(?:dongle|receiver)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return name or "无线鼠标"


def _find_protocol(interface: hid.HidInterface) -> dict | None:
    if interface.vendor_id not in ATK_VIDS:
        return None
    if interface.usage_page == 0xFF05 and interface.output_len >= 64:
        return {
            "kind": "atk2",
            "report_id": 0x08,
            "length": 64,
            "payload": [0x7D, 0x72, 0x02, 0x00, 0x01, 0x07, 0x01],
            "level_offset": 7,
            "valid": lambda data: (
                len(data) >= 8 and data[1] == 0x72 and data[5] == 0x07
            ),
        }
    if interface.usage_page == 0xFF02 and interface.output_len >= 17:
        return {
            "kind": "atk1",
            "report_id": 0x08,
            "length": 17,
            "payload": [0x04] + [0x00] * 15 + [0x49],
            "level_offset": 6,
            "valid": lambda data: len(data) >= 7 and data[0] == 0x08,
        }
    return None


def _request_report(
    device: hid.HidDevice, protocol: dict, attempts: int = 3
) -> bytes | None:
    body = bytes(
        ([protocol["report_id"]] + protocol["payload"] + [0] * protocol["length"])[
            : protocol["length"]
        ]
    )
    last: bytes | None = None
    for _ in range(attempts):
        device.drain()
        try:
            device.write_output(body)
        except hid.HidError:
            raise
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            data = device.read_input(timeout_ms=150)
            if not data:
                continue
            last = data
            if protocol["valid"](data):
                return data
    return last


def read_mouse() -> tuple[Device | None, str]:
    try:
        interfaces = hid.enumerate_hid()
    except OSError as exc:
        return None, f"无法枚举 USB 设备：{exc}"

    candidates: list[tuple[hid.HidInterface, dict]] = []
    for interface in interfaces:
        protocol = _find_protocol(interface)
        if protocol:
            candidates.append((interface, protocol))

    if not candidates:
        return None, "未检测到 2.4G 接收器，请确认接收器已插好"

    # Prefer the 64-byte FF05 protocol used by the current ATK/NK mouse.
    candidates.sort(key=lambda item: 0 if item[1]["kind"] == "atk2" else 1)
    last_error = ""
    for interface, protocol in candidates:
        try:
            with hid.HidDevice(interface.path, interface.input_len) as device:
                data = _request_report(device, protocol)
        except hid.HidError as exc:
            last_error = f"无法读取接收器：{exc}"
            continue

        if not data:
            last_error = "鼠标没有响应，动一下鼠标或按一下按键再试"
            continue
        if not protocol["valid"](data):
            last_error = "收到了接收器数据，但不是有效的电量回复"
            continue

        offset = protocol["level_offset"]
        if len(data) <= offset:
            last_error = "电量回复长度异常"
            continue
        level = int(data[offset])
        if not 0 <= level <= 100:
            last_error = f"电量数值异常（{level}）"
            continue

        voltage = None
        if protocol["kind"] == "atk2" and len(data) >= 10:
            mv = int(data[8]) | (int(data[9]) << 8)
            if 2500 <= mv <= 4500:
                voltage = mv

        name = _clean_mouse_name(interface.product)
        return (
            Device(
                key=f"2.4g:{interface.vid_pid}",
                name=name,
                transport="2.4G",
                subtitle=f"接收器 {interface.vid_pid} · 本地 HID",
                level=level,
                source="ATK / VXE HID 协议",
                voltage_mv=voltage,
            ),
            "",
        )

    return None, last_error or "鼠标暂时没有上报电量"


# ---------------------------------------------------------------------------
# Bluetooth battery reported by Windows
# ---------------------------------------------------------------------------
def _registry_string(handle, info: SP_DEVINFO_DATA, prop: int) -> str:
    buffer = ctypes.create_string_buffer(1024)
    needed = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceRegistryPropertyW(
        handle,
        ctypes.byref(info),
        prop,
        None,
        buffer,
        1024,
        ctypes.byref(needed),
    ):
        return ""
    return buffer.raw.decode("utf-16-le", errors="ignore").split("\x00")[0]


def _instance_id(handle, info: SP_DEVINFO_DATA) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceInstanceIdW(
        handle,
        ctypes.byref(info),
        buffer,
        512,
        ctypes.byref(needed),
    ):
        return ""
    return buffer.value


def _battery_property(handle, info: SP_DEVINFO_DATA) -> int | None:
    key = PROPERTYKEY(BLUETOOTH_PROPERTY, 2)
    prop_type = wintypes.ULONG(0)
    value = ctypes.c_uint32(0)
    needed = wintypes.DWORD(0)
    ok = setupapi.SetupDiGetDevicePropertyW(
        handle,
        ctypes.byref(info),
        ctypes.byref(key),
        ctypes.byref(prop_type),
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(needed),
        0,
    )
    if not ok:
        return None
    if prop_type.value not in (3, 5, 7):  # BYTE, UINT16, UINT32
        return None
    level = int(value.value) & 0xFFFF
    if 1 <= level <= 100:
        return level
    return None


def _bluetooth_nodes() -> Iterable[tuple[str, str, int]]:
    attempts = (
        (None, "BTHENUM", 0),
        (None, "BTHLE", 0),
        (ctypes.byref(CLASS_BLUETOOTH), None, DIGCF_PRESENT),
        (ctypes.byref(CLASS_SYSTEM), None, DIGCF_PRESENT),
    )
    seen: set[str] = set()
    for class_guid, enumerator, extra_flags in attempts:
        flags = DIGCF_PRESENT | extra_flags
        handle = setupapi.SetupDiGetClassDevsW(
            class_guid,
            enumerator,
            None,
            flags,
        )
        if not handle or handle == hid.INVALID_HANDLE_VALUE:
            continue
        try:
            index = 0
            while True:
                info = SP_DEVINFO_DATA()
                info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
                if not setupapi.SetupDiEnumDeviceInfo(
                    handle, index, ctypes.byref(info)
                ):
                    break
                index += 1
                instance = _instance_id(handle, info)
                if not instance.upper().startswith(("BTHENUM", "BTHLE")) or instance in seen:
                    continue
                seen.add(instance)
                name = _registry_string(handle, info, SPDRP_FRIENDLYNAME)
                if not name:
                    name = _registry_string(handle, info, SPDRP_DEVICEDESC)
                level = _battery_property(handle, info)
                if level is not None:
                    yield instance, name or "蓝牙设备", level
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(handle)


def _address_from_instance(instance: str) -> str:
    matches = re.findall(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])", instance)
    if not matches:
        return ""
    raw = matches[-1].upper()
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def _clean_bluetooth_name(name: str) -> str:
    name = re.sub(
        r"\s+(?:Hands-Free(?:\s+AG)?|Avrcp(?:\s+.*)?|A2DP(?:\s+.*)?|"
        r"SPP|RFCOMM|HFP(?:\s+.*)?|免提(?:.*)?|音频(?:.*)?)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name or "蓝牙设备"


def connected_bluetooth_addresses() -> set[str]:
    """Return addresses Windows currently reports as connected.

    A battery property can outlive the connection (Windows keeps the last
    reported percentage).  Checking the radio state prevents showing a stale
    value as if the device were live.
    """
    params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
    params.dwSize = ctypes.sizeof(params)
    params.fReturnAuthenticated = True
    params.fReturnRemembered = True
    params.fReturnConnected = True
    params.fReturnUnknown = True
    params.fIssueInquiry = False
    params.cTimeoutMultiplier = 1
    params.hRadio = None

    info = BLUETOOTH_DEVICE_INFO()
    info.dwSize = ctypes.sizeof(info)
    handle = _bthprops.BluetoothFindFirstDevice(
        ctypes.byref(params), ctypes.byref(info)
    )
    if not handle:
        return set()

    connected: set[str] = set()
    try:
        while True:
            if info.fConnected:
                raw = int(info.Address.ullLong)
                address = ":".join(
                    f"{(raw >> (8 * (5 - i))) & 0xFF:02X}" for i in range(6)
                )
                connected.add(address)
            if not _bthprops.BluetoothFindNextDevice(handle, ctypes.byref(info)):
                break
    finally:
        _bthprops.BluetoothFindDeviceClose(handle)
    return connected


def read_bluetooth() -> tuple[list[Device], str]:
    groups: dict[str, dict] = {}
    try:
        for instance, raw_name, level in _bluetooth_nodes():
            address = _address_from_instance(instance)
            clean_name = _clean_bluetooth_name(raw_name)
            group_key = address or clean_name.lower()
            current = groups.get(group_key)
            if current is None:
                groups[group_key] = {
                    "name": clean_name,
                    "raw_name": raw_name,
                    "level": level,
                    "address": address,
                }
            else:
                # Prefer the shortest, non-generic name for a physical device.
                generic = ("蓝牙外围设备", "Bluetooth Device", "未知设备")
                if (
                    clean_name not in generic
                    and len(clean_name) < len(current["name"])
                ):
                    current["name"] = clean_name
                current["level"] = max(current["level"], level)
    except OSError as exc:
        return [], f"无法读取蓝牙设备：{exc}"

    # Drop remembered devices whose battery property is only a cached value.
    connected = connected_bluetooth_addresses()
    groups = {
        key: item
        for key, item in groups.items()
        if item["address"] and item["address"] in connected
    }

    devices: list[Device] = []
    for item in groups.values():
        name = item["name"]
        devices.append(
            Device(
                key=f"bt:{item['address'] or name}",
                name=name,
                transport="蓝牙",
                subtitle=(
                    f"{item['address']} · Windows 蓝牙电量"
                    if item["address"]
                    else "Windows 蓝牙电量"
                ),
                level=int(item["level"]),
                source="Windows 蓝牙电量属性",
                address=item["address"],
            )
        )
    devices.sort(key=lambda d: (0 if d.is_mouse else 1, -d.level, d.name.lower()))
    return devices, ""


def collect() -> Snapshot:
    mouse, mouse_error = read_mouse()
    bluetooth, bluetooth_error = read_bluetooth()
    devices: list[Device] = []
    if mouse is not None:
        devices.append(mouse)
    devices.extend(bluetooth)
    return Snapshot(
        devices=devices,
        timestamp=time.time(),
        mouse_error=mouse_error,
        bluetooth_error=bluetooth_error,
    )
