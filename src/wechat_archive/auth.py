import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import ArchiveError, SessionExpired
from .urls import same_origin


def default_session_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "wechat-article-archive" / "session.json"


def load_session(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SessionExpired("没有可用的本地登录状态，请先运行 wechat-archive login。") from None
    if not isinstance(data, dict) or not str(data.get("token", "")).isdigit():
        raise SessionExpired("本地登录状态格式不正确，请重新运行 wechat-archive login。")
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise SessionExpired("本地登录状态缺少 Cookie，请重新登录。")
    return data


def save_session(path: Path, token: str, cookies: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": token, "cookies": cookies}, stream, ensure_ascii=False)
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def login(path: Path, timeout: int = 300) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ArchiveError(
            '扫码登录需要安装：pip install "wechat-article-archive[login]"，'
            "然后运行 playwright install chromium。"
        ) from None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded")
                print("请在新窗口中扫码登录你自己的微信公众号后台。登录状态只保存在本机。")
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if page.is_closed():
                        raise ArchiveError("登录窗口已关闭，没有保存登录状态。")
                    token = parse_qs(urlparse(page.url).query).get("token", [""])[0]
                    if same_origin(page.url) and token.isdigit():
                        cookies = context.cookies("https://mp.weixin.qq.com/")
                        if cookies:
                            save_session(path, token, cookies)
                            return
                    page.wait_for_timeout(500)
                raise SessionExpired("等待扫码登录超时，没有保存登录状态。")
            finally:
                browser.close()
    except PlaywrightError:
        raise ArchiveError(
            "无法启动或读取登录浏览器。请运行 playwright install chromium 后再试。"
        ) from None
