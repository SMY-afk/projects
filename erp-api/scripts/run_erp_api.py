from __future__ import annotations

import platform
import runpy


def main() -> None:
    # A degraded Windows WMI provider must not block SQLAlchemy imports.
    platform._wmi = None  # type: ignore[attr-defined]
    runpy.run_module("erp_api", run_name="__main__")


if __name__ == "__main__":
    main()
