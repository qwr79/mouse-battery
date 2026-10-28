"""Minimal, dependency-free HID access for Windows.

Only the pieces needed by MouseBattery are implemented: enumerate HID
interfaces, inspect their caps, send an output report and read input
reports through a separate overlapped handle.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10

FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102

HIDP_STATUS_SUCCESS = 0x00110000


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


HID_GUID = GUID(
    0x4D1E55B2,
    0xF16F,
    0x11CF,
    (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30),
)


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", ctypes.c_void_p),
    ]


setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID),
    wintypes.LPCWSTR,
    wintypes.HWND,
    wintypes.DWORD,
]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(GUID),
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.ReadFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(OVERLAPPED),
]
kernel32.WriteFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetOverlappedResult.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL,
]
kernel32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]

hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidD_GetProductString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.ULONG,
]
hid.HidD_GetManufacturerString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.ULONG,
]
hid.HidD_SetOutputReport.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.ULONG,
]


def _read_wide_string(function, handle: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if function(handle, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


def _device_paths() -> Iterator[str]:
    handle = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(HID_GUID), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return
    try:
        index = 0
        while True:
            interface = SP_DEVICE_INTERFACE_DATA()
            interface.cbSize = ctypes.sizeof(interface)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                handle, None, ctypes.byref(HID_GUID), index, ctypes.byref(interface)
            ):
                break
            index += 1
            required = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle,
                ctypes.byref(interface),
                None,
                0,
                ctypes.byref(required),
                None,
            )
            if not required.value:
                continue
            buffer = ctypes.create_string_buffer(required.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on x64, 6 on x86.
            ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0] = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            )
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle,
                ctypes.byref(interface),
                buffer,
                required.value,
                None,
                None,
            ):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buffer) + 4)
            if path:
                yield path
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)


@dataclass(frozen=True)
class HidInterface:
    path: str
    vendor_id: int
    product_id: int
    usage_page: int
    usage: int
    input_len: int
    output_len: int
    feature_len: int
    product: str
    manufacturer: str

    @property
    def vid_pid(self) -> str:
        return f"{self.vendor_id:04X}:{self.product_id:04X}"


def _probe(path: str) -> HidInterface | None:
    handle = kernel32.CreateFileW(
        path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        attributes = HIDD_ATTRIBUTES()
        attributes.Size = ctypes.sizeof(attributes)
        if not hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
            return None

        caps = HIDP_CAPS()
        preparsed = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)) and preparsed:
            try:
                if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                    return None
            finally:
                hid.HidD_FreePreparsedData(preparsed)
        else:
            return None

        return HidInterface(
            path=path,
            vendor_id=int(attributes.VendorID),
            product_id=int(attributes.ProductID),
            usage_page=int(caps.UsagePage),
            usage=int(caps.Usage),
            input_len=int(caps.InputReportByteLength),
            output_len=int(caps.OutputReportByteLength),
            feature_len=int(caps.FeatureReportByteLength),
            product=_read_wide_string(hid.HidD_GetProductString, handle),
            manufacturer=_read_wide_string(hid.HidD_GetManufacturerString, handle),
        )
    except OSError:
        return None
    finally:
        kernel32.CloseHandle(handle)


def enumerate_hid() -> list[HidInterface]:
    interfaces: list[HidInterface] = []
    for path in _device_paths():
        interface = _probe(path)
        if interface is not None:
            interfaces.append(interface)
    return interfaces


class HidError(OSError):
    pass


class HidDevice:
    """A HID interface with separate write and overlapped read handles."""

    def __init__(self, path: str, input_len: int):
        self.path = path
        self.input_len = input_len
        self.write_handle = kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not self.write_handle or self.write_handle == INVALID_HANDLE_VALUE:
            error = ctypes.get_last_error()
            raise HidError(f"无法打开设备（错误 {error}）", error)

        self.read_handle = kernel32.CreateFileW(
            path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if not self.read_handle or self.read_handle == INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(self.write_handle)
            error = ctypes.get_last_error()
            raise HidError(f"无法打开读取通道（错误 {error}）", error)

        self.event = kernel32.CreateEventW(None, True, False, None)
        if not self.event:
            kernel32.CloseHandle(self.write_handle)
            kernel32.CloseHandle(self.read_handle)
            raise HidError("无法创建读取事件")

    def __enter__(self) -> "HidDevice":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "read_handle", None):
            kernel32.CancelIoEx(self.read_handle, None)
            kernel32.CloseHandle(self.read_handle)
            self.read_handle = None
        if getattr(self, "event", None):
            kernel32.CloseHandle(self.event)
            self.event = None
        if getattr(self, "write_handle", None):
            kernel32.CloseHandle(self.write_handle)
            self.write_handle = None

    def write_output(self, report: bytes) -> None:
        buffer = ctypes.create_string_buffer(bytes(report), len(report))
        if hid.HidD_SetOutputReport(self.write_handle, buffer, len(report)):
            return
        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(
            self.write_handle, buffer, len(report), ctypes.byref(written), None
        ):
            error = ctypes.get_last_error()
            raise HidError(f"发送失败（错误 {error}）", error)

    def read_input(self, timeout_ms: int = 600) -> bytes | None:
        if not self.input_len:
            return None
        length = self.input_len
        buffer = ctypes.create_string_buffer(length)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self.event
        read = wintypes.DWORD(0)
        kernel32.ResetEvent(self.event)

        ok = kernel32.ReadFile(
            self.read_handle,
            buffer,
            length,
            ctypes.byref(read),
            ctypes.byref(overlapped),
        )
        if ok:
            return buffer.raw[: read.value]

        if ctypes.get_last_error() != ERROR_IO_PENDING:
            return None

        result = kernel32.WaitForSingleObject(self.event, max(1, timeout_ms))
        if result == WAIT_OBJECT_0:
            done = wintypes.DWORD(0)
            if kernel32.GetOverlappedResult(
                self.read_handle, ctypes.byref(overlapped), ctypes.byref(done), False
            ):
                return buffer.raw[: done.value]
            return None

        kernel32.CancelIoEx(self.read_handle, ctypes.byref(overlapped))
        kernel32.WaitForSingleObject(self.event, 100)
        done = wintypes.DWORD(0)
        kernel32.GetOverlappedResult(
            self.read_handle, ctypes.byref(overlapped), ctypes.byref(done), False
        )
        return None

    def drain(self, attempts: int = 24) -> None:
        if not self.input_len:
            return
        for _ in range(attempts):
            if self.read_input(timeout_ms=4) is None:
                break
