import hashlib
from urllib.parse import parse_qs, urlencode, urlparse

from .errors import ArchiveError


def article_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "mp.weixin.qq.com"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or not (parsed.path == "/s" or parsed.path.startswith("/s/"))
    ):
        raise ArchiveError("需要 https://mp.weixin.qq.com/s/… 或 /s?… 格式的微信原文链接。")
    query = parse_qs(parsed.query)
    keys = ("__biz", "mid", "idx", "sn")
    if parsed.path == "/s":
        if not query.get("__biz") or not query.get("mid"):
            raise ArchiveError("微信长链接缺少 __biz 或 mid。")
        return "https://mp.weixin.qq.com/s?" + urlencode(
            {key: query[key][0] for key in keys if query.get(key)}
        )
    return "https://mp.weixin.qq.com" + parsed.path.rstrip("/")


def article_key(url: str) -> str:
    return hashlib.sha256(article_url(url).encode()).hexdigest()[:16]


def same_origin(url: str) -> bool:
    p = urlparse(url)
    return (
        p.scheme == "https"
        and p.hostname == "mp.weixin.qq.com"
        and p.port in (None, 443)
        and not p.username
        and not p.password
    )
