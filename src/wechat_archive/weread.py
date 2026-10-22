"""Optional personal-WeChat route through the versioned weread-omni CLI.

The upstream client owns device authentication. This adapter only invokes read operations,
and always fetches article bodies from the publisher's original mp.weixin.qq.com URL.
"""

import json
import os
import shutil
import subprocess
import time

from .accounts import Account, HistoryPage
from .errors import ArchiveError, SessionExpired, UnexpectedResponse
from .urls import article_url


def executable() -> str:
    candidate = os.environ.get("WEREAD_OMNI_BIN") or shutil.which("weread-omni")
    if not candidate:
        raise ArchiveError(
            "无需公众号后台的方式需要 Node.js >=22.13 和 weread-omni："
            "npm install -g weread-omni@0.1.2；然后运行 wechat-archive login。"
        )
    return candidate


def login_personal() -> int:
    # No shell, no browser-cookie extraction, no credentials passed on the command line.
    return subprocess.call([executable(), "login"])


class WeReadClient:
    def __init__(self, binary: str | None = None, runner=subprocess.run, sleeper=time.sleep):
        self.binary = binary or executable()
        self.runner = runner
        self.sleep = sleeper

    def _call(self, *arguments: str) -> dict:
        try:
            result = self.runner(
                [self.binary, *arguments, "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ArchiveError("微信读书客户端无法运行或请求超时，进度已保留。") from None
        if result.returncode:
            # Never echo upstream stderr: it may contain local paths or session diagnostics.
            raise SessionExpired(
                "微信读书请求失败，请先运行 weread-omni doctor --json 检查登录与访问限制；"
                "必要时重新运行 wechat-archive login。不会将此情况视为历史列表结束。"
            )
        try:
            data = json.loads(result.stdout)
        except (TypeError, ValueError):
            raise UnexpectedResponse("微信读书客户端没有返回有效 JSON。") from None
        if not isinstance(data, dict):
            raise UnexpectedResponse("微信读书客户端返回格式已改变。")
        return data

    def search(self, query: str) -> list[Account]:
        found = {}
        cursor = None
        for page_number in range(20):
            args = ["search", "books", query, "--scope", "2", "--count", "20"]
            if cursor is not None:
                args.extend(["--max-idx", str(cursor)])
            data = self._call(*args)
            entries = data.get("books")
            if not isinstance(entries, list):
                raise UnexpectedResponse("微信读书搜索结果缺少 books。")
            for item in entries:
                book = item.get("bookInfo", item) if isinstance(item, dict) else {}
                book_id = str(book.get("bookId", ""))
                if book_id.startswith("MP_WXS_") and book.get("title"):
                    found[book_id] = Account(book["title"], "", book_id)
            if data.get("hasMore") not in (1, True):
                return list(found.values())
            next_cursor = entries[-1].get("searchIdx") if entries else None
            if next_cursor is None or next_cursor == cursor:
                raise UnexpectedResponse("微信读书搜索没有有效的下一页，无法核对同名公众号。")
            cursor = next_cursor
            if page_number < 19:
                self.sleep(2)
        raise UnexpectedResponse("公众号搜索超过安全页数，请使用更准确的名称。")

    def history(self, account: Account, begin: int, count: int = 50) -> HistoryPage:
        args = ["public-accounts", "articles", account.account_id, "--count", str(count)]
        # The first request must omit --offset; synckey is not a pagination cursor.
        if begin:
            args.extend(["--offset", str(begin)])
        data = self._call(*args)
        entries = data.get("articles")
        if not isinstance(entries, list):
            raise UnexpectedResponse("微信读书历史列表缺少 articles。")
        rows = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise UnexpectedResponse("微信读书文章格式已改变。")
            info = entry.get("mpInfo") or {}
            if not isinstance(info, dict):
                raise UnexpectedResponse("微信读书文章缺少有效 mpInfo。")
            link = info.get("doc_url")
            if not link:
                review_id = entry.get("reviewId")
                if not review_id:
                    raise UnexpectedResponse("微信读书文章没有原文链接或 reviewId。")
                self.sleep(2)
                detail = self._call("review", "single", str(review_id))
                review = detail.get("review") or {}
                info = review.get("mpInfo") or {}
                link = info.get("doc_url")
            if not link:
                raise UnexpectedResponse("微信读书未返回原文链接，未用不透明 ID 拼接假链接。")
            rows.append(
                {
                    "url": article_url(link),
                    "title": info.get("title") or entry.get("title", ""),
                    "published_timestamp": info.get("time") or entry.get("createTime"),
                }
            )
        next_offset = data.get("nextOffset")
        if next_offset is not None and (type(next_offset) is not int or next_offset <= begin):
            raise UnexpectedResponse("微信读书返回的下一页位置无效。")
        if next_offset is None and data.get("hasMore") in (1, True):
            raise UnexpectedResponse("微信读书声称仍有文章，却没有提供下一页位置。")
        return HistoryPage(rows, len(entries), None, next_offset, next_offset is None)
