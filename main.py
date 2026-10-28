from __future__ import annotations

import json
import sys

from mouse_battery import __version__, devices


def main() -> int:
    if "--version" in sys.argv:
        print(__version__)
        return 0
    if "--once" in sys.argv or "--json" in sys.argv:
        snapshot = devices.collect()
        if "--json" in sys.argv:
            payload = {
                "timestamp": snapshot.timestamp,
                "mouse_error": snapshot.mouse_error,
                "devices": [
                    {
                        "name": device.name,
                        "transport": device.transport,
                        "level": device.level,
                        "voltage_mv": device.voltage_mv,
                        "address": device.address,
                        "source": device.source,
                    }
                    for device in snapshot.devices
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        for device in snapshot.devices:
            extra = f"  {device.voltage_mv / 1000:.2f} V" if device.voltage_mv else ""
            print(f"{device.name}  [{device.transport}]  {device.level}%{extra}")
        if not snapshot.devices:
            print(snapshot.mouse_error or "没有找到可读取电量的设备")
        if snapshot.mouse_error and snapshot.devices:
            print(f"提示：{snapshot.mouse_error}")
        return 0 if snapshot.devices else 1

    from mouse_battery.ui import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
