import json
from unittest.mock import Mock

import pytest
import requests

from wechat_archive.article import parse_article
from wechat_archive.errors import ArchiveError, UnexpectedResponse, VerificationRequired
from wechat_archive.http import ArticleClient
from wechat_archive.storage import save_article, saved_article_exists
from wechat_archive.urls import article_url

URL = "https://mp.weixin.qq.com/s/synthetic-article"


def test_nested_body_images_metadata_and_saved_outputs(original_html, tmp_path):
    article = parse_article(original_html, URL)
    assert article.title == "测试文章：嵌套正文"
    assert article.account == "测试公众号"
    assert article.author == "测试作者"
    assert article.published_at == "2026-10-14T19:56:20+08:00"
    assert "最后一段，必须完整保留。" in article.text
    assert "导航" not in article.text and "hidden()" not in article.text
    assert "**重点内容**" in article.markdown
    assert article.images == ["https://mmbiz.qpic.cn/test.jpg"]
    assert article.markdown.index("test.jpg") < article.markdown.index("最后一段")
    saved = save_article(article, tmp_path)
    assert saved_article_exists(saved, tmp_path)
    metadata = json.loads((tmp_path / saved["files"]["json"]).read_text())
    assert metadata["source_url"] == URL
    assert metadata["text"] == article.text
    (tmp_path / saved["files"]["md"]).write_text("corrupted", encoding="utf-8")
    assert not saved_article_exists(saved, tmp_path)


@pytest.mark.parametrize(
    "page,exception",
    [
        ("<html><h2>环境异常</h2><p>完成验证后继续</p></html>", VerificationRequired),
        ("<h1>此内容已被发布者删除</h1>", UnexpectedResponse),
        ('<h1 id="activity-name">标题</h1><div id="js_content"></div>', UnexpectedResponse),
    ],
)
def test_errors_are_not_articles(page, exception):
    with pytest.raises(exception):
        parse_article(page, URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://mp.weixin.qq.com/s/a",
        "https://example.com/s/a",
        "https://mp.weixin.qq.com.evil.test/s/a",
        "https://user:secret@mp.weixin.qq.com/s/a",
        "https://mp.weixin.qq.com:8443/s/a",
        "https://mp.weixin.qq.com/cgi-bin/searchbiz",
        "https://mp.weixin.qq.com/s?foo=1",
    ],
)
def test_only_original_article_urls_are_accepted(url):
    with pytest.raises(ArchiveError):
        article_url(url)


def test_tracking_parameters_do_not_duplicate_article():
    assert article_url(URL + "?scene=1#rd") == URL
    long = "https://mp.weixin.qq.com/s?__biz=test&mid=1&idx=2&sn=hash&scene=1#rd"
    assert article_url(long).endswith("__biz=test&mid=1&idx=2&sn=hash")


def test_known_paid_preview_is_not_a_complete_article(original_html):
    page = original_html.replace("</body>", "<mp-pay-preview></mp-pay-preview></body>")
    with pytest.raises(UnexpectedResponse, match="付费预览"):
        parse_article(page, URL)


def response(status=200, text="", headers=None):
    return Mock(status_code=status, text=text, headers=headers or {})


def test_fetch_falls_back_without_accepting_captcha(original_html):
    client = ArticleClient()
    client.session.get = Mock(
        side_effect=[
            response(302, headers={"Location": "/mp/wappoc_appmsgcaptcha?secret=ignored"}),
            response(text=original_html),
        ]
    )
    article = client.fetch(URL)
    assert article.title == "测试文章：嵌套正文"
    assert client.session.get.call_count == 2


def test_redirect_cannot_send_request_to_another_host():
    client = ArticleClient()
    client.session.get = Mock(return_value=response(302, headers={"Location": "https://evil.test"}))
    with pytest.raises(ArchiveError, match="微信以外"):
        client.fetch(URL)
    assert client.session.get.call_count == 1


def test_network_error_does_not_expose_url_secrets():
    client = ArticleClient()
    client.session.get = Mock(side_effect=requests.ConnectionError("token=DO_NOT_PRINT"))
    with pytest.raises(ArchiveError) as error:
        client.fetch(URL)
    assert "DO_NOT_PRINT" not in str(error.value)
