"""Centralized runtime configuration.

All settings can be overridden via environment variables (prefixed with `EK_`)
or by editing the defaults below. A `.env` file in the project root is
automatically loaded if present.

Cross-platform notes:
- `chrome_path` is auto-detected for macOS, Linux, and Windows. Override with
  `EK_CHROME_PATH` if your install lives elsewhere.
"""
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


# --- Optional .env loading (no extra dependency required) ---
def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# --- Chrome auto-detection ---
def _default_chrome_path() -> str:
    system = platform.system()
    candidates: list[str] = []
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    elif system == "Linux":
        candidates = [
            shutil.which("google-chrome") or "",
            shutil.which("google-chrome-stable") or "",
            shutil.which("chromium") or "",
            shutil.which("chromium-browser") or "",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return ""  # let nodriver attempt its own detection


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Site
    base_url: str = os.environ.get("EK_BASE_URL", "https://www.enterkomputer.com/")
    sitemap_url: str = os.environ.get(
        "EK_SITEMAP_URL", "https://www.enterkomputer.com/sitemap.xml"
    )

    # Browser
    chrome_path: str = os.environ.get("EK_CHROME_PATH") or _default_chrome_path()
    show_browser: bool = _env_bool("EK_SHOW_BROWSER", default=False)
    cf_wait_secs: int = _env_int("EK_CF_WAIT_SECS", 30)
    offscreen_position: str = os.environ.get("EK_OFFSCREEN_POSITION", "-2400,-2400")
    window_size: str = os.environ.get("EK_WINDOW_SIZE", "1280,800")

    # Discovery
    discover_delay: float = _env_float("EK_DISCOVER_DELAY", 3.0)
    load_more_max_clicks: int = _env_int("EK_LOAD_MORE_MAX_CLICKS", 50)
    load_more_wait: float = _env_float("EK_LOAD_MORE_WAIT", 1.5)

    # HTTP impersonation profile for curl_cffi
    impersonate: str = os.environ.get("EK_IMPERSONATE", "chrome120")

    def browser_args(self) -> list[str]:
        """Args passed to Chrome at launch.

        When `show_browser` is False, the window is positioned offscreen so
        the user doesn't see it. Pure headless (--headless=new) is detected
        by Cloudflare Turnstile and gets blocked, hence this workaround.
        """
        if self.show_browser:
            return []
        return [
            f"--window-position={self.offscreen_position}",
            f"--window-size={self.window_size}",
        ]


CONFIG = Config()


def require_chrome_path() -> str:
    """Return the configured Chrome path, raising a friendly error if unset."""
    if CONFIG.chrome_path and Path(CONFIG.chrome_path).exists():
        return CONFIG.chrome_path
    raise RuntimeError(
        "Could not locate Google Chrome. Install Chrome (or Chromium/Brave) "
        "or set EK_CHROME_PATH in your environment / .env file. "
        f"Detected platform: {platform.system()}. "
        f"Tried: {CONFIG.chrome_path or '(none found)'}"
    )
