"""Compile-time installation identity; never selected by environment or CLI flags."""

import os
from dataclasses import dataclass
from pathlib import Path

from . import build_target

OFFLINE_ORIGIN = "https://collector-offline.invalid"


@dataclass(frozen=True)
class Identity:
    name: str
    display_name: str
    profile_directory: str
    autostart_value: str
    mutex: str
    app_id: str


PRODUCTION = Identity(
    "production",
    "Tanren Collector",
    "TanrenCollector",
    "TanrenCollector",
    r"Local\TanrenCollector.Desktop",
    "A40F8247-D97C-4BB5-A778-452509E35053",
)
ENGINEERING = Identity(
    "engineering",
    "Tanren Collector Engineering",
    "TanrenCollectorEngineering",
    "TanrenCollectorEngineering",
    r"Local\TanrenCollector.Engineering.Desktop",
    "C7E48B92-68D5-4C31-9177-503BA7F62DB8",
)


def current() -> Identity:
    name = getattr(build_target, "BUILD_PROFILE", "production")
    if name == "production":
        return PRODUCTION
    if name != "engineering" or build_target.ORIGIN != OFFLINE_ORIGIN:
        raise RuntimeError("INVALID_BUILD_PROFILE")
    return ENGINEERING


def profile_root() -> Path:
    if not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("WINDOWS_USER_PROFILE_REQUIRED")
    return Path(os.environ["LOCALAPPDATA"]) / current().profile_directory


def check_storage_path(path: str | Path) -> None:
    """Reject cross-profile paths and junction/symlink escapes before any file access."""
    if current() == ENGINEERING:
        expected = Path(os.environ["LOCALAPPDATA"]).resolve() / ENGINEERING.profile_directory
        if not Path(path).resolve().is_relative_to(expected):
            raise RuntimeError("ENGINEERING_PROFILE_PATH_REQUIRED")


def require_native_mt5() -> None:
    if current() == ENGINEERING:
        raise RuntimeError("ENGINEERING_MT5_DISABLED")


def require_network() -> None:
    if current() == ENGINEERING:
        raise RuntimeError("ENGINEERING_OFFLINE")


def configure_engineering_log() -> None:
    if current() != ENGINEERING:
        return
    import logging
    from logging.handlers import RotatingFileHandler

    path = profile_root() / "engineering.log"
    check_storage_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s ENGINEERING %(levelname)s %(message)s"))
    logger = logging.getLogger("tanren_collector.engineering")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    logger.info("Offline engineering profile started; MT5 and network disabled")
