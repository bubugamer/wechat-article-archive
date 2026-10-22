import json
import time
from dataclasses import asdict, dataclass

import requests

from .errors import (
    AccountNotFound,
    AmbiguousAccount,
    ArchiveError,
    RateLimited,
    SessionExpired,
    UnexpectedResponse,
    VerificationRequired,
)
from .http import DESKTOP_UA
from .urls import article_url


@dataclass
class Account:
    name: str
    alias: str
    account_id: str
    signature: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HistoryPage:
    articles: list[dict]
    record_count: int
    total_records: int | None
    next_offset: int | None = None
    is_last: bool = False


def json_object(value, label: str) -> dict:
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise UnexpectedResponse(f"微信返回的{label}无法解析，已停止，避免漏掉文章。") from None
    if not isinstance(value, dict):
        raise UnexpectedResponse(f"微信返回的{label}格式改变，已停止。")
    return value


def parse_history(payload: dict) -> HistoryPage:
    page = json_object(payload.get("publish_page"), "历史列表")
    total = page.get("total_count")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise UnexpectedResponse("微信历史列表缺少可靠的总记录数，无法确认已获取全部文章。")
    records = page.get("publish_list")
    if not isinstance(records, list):
        raise UnexpectedResponse("微信历史列表缺少 publish_list。")
    articles = []
    for record in records:
        if not isinstance(record, dict):
            raise UnexpectedResponse("微信发布记录格式改变。")
        info = json_object(record.get("publish_info"), "发布记录")
        entries = info.get("appmsgex")
        if not isinstance(entries, list) or not entries:
            raise UnexpectedResponse("发布记录中没有可解析的文章，无法确认历史完整。")
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("link"):
                raise UnexpectedResponse("发布记录中的文章缺少原文链接。")
            articles.append(
                {
                    "url": article_url(entry["link"]),
                    "title": entry.get("title", ""),
                    "published_timestamp": entry.get("create_time") or entry.get("update_time"),
                    "author": entry.get("author_name", ""),
                }
            )
    return HistoryPage(articles, len(records), total)


def select_account(candidates: list[Account], query: str, account_id: str | None = None) -> Account:
    if account_id:
        matches = [a for a in candidates if a.account_id == account_id]
    else:
        matches = [a for a in candidates if a.name == query or a.alias == query]
    if len(matches) == 1:
        return matches[0]
    if not matches and not candidates:
        raise AccountNotFound(f"没有找到公众号：{query}")
    choices = matches or candidates
    detail = "；".join(
        f"{a.name}（微信号 {a.alias or '未提供'}，ID {a.account_id}）" for a in choices
    )
    raise AmbiguousAccount(f"无法唯一确认目标公众号。候选：{detail}。请指定 --account-id。")


class BackendClient:
    """Read the backend's account search and history; never create or send a draft."""

    def __init__(self, credentials: dict, retries: int = 3, sleeper=time.sleep):
        self.token = str(credentials["token"])
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": DESKTOP_UA, "Referer": "https://mp.weixin.qq.com/"}
        )
        for cookie in credentials["cookies"]:
            domain = str(cookie.get("domain", "")).lstrip(".")
            if domain not in ("mp.weixin.qq.com", "weixin.qq.com"):
                continue
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", domain),
                path=cookie.get("path", "/"),
                secure=True,
            )
        if not self.session.cookies:
            raise SessionExpired("登录状态没有微信公众号后台的 Cookie，请重新登录。")
        self.retries = retries
        self.sleep = sleeper

    def _get(self, endpoint: str, params: dict) -> dict:
        params = {**params, "token": self.token, "lang": "zh_CN", "f": "json", "ajax": 1}
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    "https://mp.weixin.qq.com/cgi-bin/" + endpoint,
                    params=params,
                    timeout=(10, 30),
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise ArchiveError(
                    f"微信公众号后台网络请求失败（{type(exc).__name__}），进度已保留。"
                ) from None
            if response.status_code in (301, 302, 303, 307, 308, 401, 403):
                raise SessionExpired("公众号后台登录已失效或无访问权限，请重新扫码登录。")
            if response.status_code == 429:
                ret = 200013
                payload = {}
            else:
                if response.status_code >= 400:
                    raise UnexpectedResponse(f"公众号后台返回 HTTP {response.status_code}。")
                try:
                    payload = response.json()
                except ValueError:
                    if any(t in response.text for t in ("环境异常", "去验证", "captcha")):
                        raise VerificationRequired("公众号后台要求人工验证，进度已保留。") from None
                    raise SessionExpired("公众号后台未返回有效列表，请重新扫码登录。") from None
                payload = json_object(payload, "接口响应")
                base = payload.get("base_resp")
                if not isinstance(base, dict) or "ret" not in base:
                    raise UnexpectedResponse("公众号后台响应缺少 base_resp.ret。")
                ret = base["ret"]
            if ret == 0:
                return payload
            if ret in (200013, 45009):
                if attempt < self.retries:
                    self.sleep(min(5 * 2**attempt, 30))
                    continue
                raise RateLimited("微信持续限制请求频率，请稍后重跑同一命令；已有文件会保留。")
            if ret in (200003, 200002, 40001, 40014, 42001, -3):
                raise SessionExpired("公众号后台登录已失效或无权限，请重新运行 login。")
            raise UnexpectedResponse(f"公众号后台返回错误码 {ret}，进度已保留。")
        raise RateLimited("微信持续限制请求频率。")

    def search(self, query: str) -> list[Account]:
        candidates = []
        seen = set()
        # The backend itself caps search visibility. Never treat the first fuzzy hit as a match.
        for begin in range(0, 100, 5):
            payload = self._get(
                "searchbiz", {"action": "search_biz", "begin": begin, "count": 5, "query": query}
            )
            entries = payload.get("list")
            if not isinstance(entries, list):
                raise UnexpectedResponse("公众号搜索结果缺少 list。")
            for row in entries:
                if not isinstance(row, dict) or not row.get("fakeid") or not row.get("nickname"):
                    raise UnexpectedResponse("公众号搜索结果缺少名称或身份标识。")
                if row["fakeid"] not in seen:
                    candidates.append(
                        Account(
                            row["nickname"],
                            row.get("alias", ""),
                            row["fakeid"],
                            row.get("signature", ""),
                        )
                    )
                    seen.add(row["fakeid"])
            if len(entries) < 5:
                break
            self.sleep(2)
        return candidates

    def history(self, account: Account, begin: int, count: int = 5) -> HistoryPage:
        payload = self._get(
            "appmsgpublish",
            {
                "sub": "list",
                "search_field": "null",
                "begin": begin,
                "count": count,
                "query": "",
                "fakeid": account.account_id,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
            },
        )
        page = parse_history(payload)
        page.next_offset = begin + page.record_count
        page.is_last = page.next_offset >= page.total_records
        return page
