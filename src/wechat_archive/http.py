from urllib.parse import urljoin

import requests

from .article import Article, parse_article
from .errors import ArchiveError, UnexpectedResponse, VerificationRequired
from .urls import article_url, same_origin

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
WECHAT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.60 NetType/WIFI Language/zh_CN"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


class ArticleClient:
    """Read original pages without borrowing backend login cookies."""

    def __init__(self, timeout: float = 30):
        self.session = requests.Session()
        self.timeout = timeout

    def fetch(self, url: str) -> Article:
        original = article_url(url)
        last_error = None
        for agent in (MOBILE_UA, WECHAT_UA, DESKTOP_UA):
            try:
                return parse_article(self._read(original, agent), original)
            except (UnexpectedResponse, VerificationRequired) as exc:
                last_error = exc
        raise last_error or UnexpectedResponse("未取得微信原文正文。")

    def _read(self, url: str, agent: str) -> str:
        try:
            for _ in range(6):
                if not same_origin(url):
                    raise ArchiveError("原文跳转到了微信以外的网站，已停止请求。")
                response = self.session.get(
                    url,
                    headers={"User-Agent": agent, "Accept-Language": "zh-CN,zh;q=0.9"},
                    timeout=(10, self.timeout),
                    allow_redirects=False,
                )
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("Location", ""))
                    if "appmsgcaptcha" in url:
                        raise VerificationRequired("微信要求人工验证，尚未取得原文正文。")
                    continue
                if response.status_code == 429:
                    raise VerificationRequired("微信限制了请求频率，请稍后重试。")
                if response.status_code >= 400:
                    raise UnexpectedResponse(f"微信原文返回 HTTP {response.status_code}。")
                response.encoding = "utf-8"
                return response.text
        except requests.RequestException as exc:
            raise ArchiveError(
                f"网络读取失败（{type(exc).__name__}），请检查网络后重试。"
            ) from None
        raise UnexpectedResponse("微信原文跳转次数过多，未取得正文。")
