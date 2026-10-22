import hashlib
import html
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from markdownify import markdownify

from .errors import UnexpectedResponse, VerificationRequired
from .urls import article_url

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class Article:
    source_url: str
    title: str
    account: str
    author: str
    published_at: str
    business_id: str
    markdown: str
    text: str
    images: list[str]
    fetched_at: str
    content_sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def js_string(page: str, name: str) -> str:
    pattern = r"\bvar\s+" + re.escape(name) + r"\s*=\s*(['\"])(.*?)\1"
    match = re.search(pattern, page, re.S)
    if not match:
        return ""
    value = match.group(2)
    value = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), value)
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), value)
    return html.unescape(value.replace(r"\/", "/").replace(r"\'", "'").replace(r"\"", '"'))


def parse_article(page: str, url: str) -> Article:
    soup = BeautifulSoup(page, "html.parser")
    body = soup.find(id="js_content")
    if body is None:
        visible = soup.get_text(" ", strip=True)
        if any(x in visible for x in ("环境异常", "完成验证", "去验证", "访问过于频繁")):
            raise VerificationRequired("微信要求人工验证，尚未取得原文正文。")
        raise UnexpectedResponse("微信页面没有原文正文，可能已删除、受限或页面结构已改变。")
    if soup.select_one("mp-pay-preview, #js_paywall, #js_pay_area, .js_pay_preview"):
        raise UnexpectedResponse("页面包含付费预览提示，未将预览保存为完整正文。")
    title_node = soup.find(id="activity-name")
    account_node = soup.find(id="js_name")
    title = title_node.get_text(" ", strip=True) if title_node else js_string(page, "msg_title")
    account = (
        account_node.get_text(" ", strip=True) if account_node else js_string(page, "nickname")
    )
    for tag in body.find_all(["script", "style", "noscript"]):
        tag.decompose()
    images = []
    for img in body.find_all("img"):
        source = img.get("data-src") or img.get("src") or ""
        if urlparse(source).scheme not in ("http", "https"):
            img.decompose()
            continue
        img["src"] = source
        img["alt"] = img.get("alt") or "原文图片"
        images.append(source)
    text = body.get_text("\n", strip=True)
    if not title or not text.strip():
        raise UnexpectedResponse("页面缺少标题或文字正文，未保存为空文章。")
    for link in body.find_all("a", href=True):
        if urlparse(link["href"]).scheme not in ("http", "https", "mailto", ""):
            del link["href"]
    content = markdownify(str(body), heading_style="ATX", strip=["svg", "iframe"]).strip()
    content = re.sub(r"\n{3,}", "\n\n", content)
    timestamp = js_string(page, "ct") or js_string(page, "oriCreateTime")
    published = js_string(page, "createTime")
    if timestamp.isdigit():
        published = datetime.fromtimestamp(int(timestamp), SHANGHAI).isoformat()
    return Article(
        source_url=article_url(url),
        title=title,
        account=account,
        author=js_string(page, "author") or js_string(page, "ori_author"),
        published_at=published,
        business_id=js_string(page, "biz"),
        markdown=content,
        text=text,
        images=list(dict.fromkeys(images)),
        fetched_at=datetime.now(SHANGHAI).isoformat(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )
