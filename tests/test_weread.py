import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from wechat_archive.accounts import Account
from wechat_archive.errors import SessionExpired, UnexpectedResponse
from wechat_archive.weread import WeReadClient


def result(data):
    return CompletedProcess([], 0, json.dumps(data), "")


def client_with(*pages):
    runner = Mock(side_effect=[result(p) for p in pages])
    return WeReadClient(binary="test-weread", runner=runner, sleeper=Mock()), runner


def test_personal_account_search_maps_ids_and_filters_books():
    client, _ = client_with(
        {
            "books": [
                {"bookInfo": {"bookId": "MP_WXS_123", "title": "测试公众号"}},
                {"bookInfo": {"bookId": "123", "title": "普通图书"}},
            ],
            "hasMore": 0,
        }
    )
    assert client.search("测试公众号") == [Account("测试公众号", "", "MP_WXS_123")]


def test_first_history_request_omits_offset_and_next_page_uses_next_offset():
    entry = {
        "reviewId": "test",
        "mpInfo": {"title": "标题", "doc_url": "https://mp.weixin.qq.com/s/synthetic-test"},
    }
    client, runner = client_with(
        {"articles": [entry], "nextOffset": 50, "synckey": 999},
        {"articles": []},
    )
    first = client.history(Account("测试公众号", "", "MP_WXS_123"), 0)
    assert first.next_offset == 50 and not first.is_last
    assert "--offset" not in runner.call_args_list[0].args[0]
    second = client.history(Account("测试公众号", "", "MP_WXS_123"), first.next_offset)
    assert second.is_last
    assert runner.call_args_list[1].args[0][-3:] == ["--offset", "50", "--json"]


def test_opaque_article_id_is_resolved_via_detail_not_concatenated():
    client, _ = client_with(
        {"articles": [{"reviewId": "opaque-review-id"}]},
        {
            "review": {
                "mpInfo": {
                    "title": "原文标题",
                    "doc_url": "https://mp.weixin.qq.com/s/original-link",
                }
            }
        },
    )
    page = client.history(Account("测试号", "", "MP_WXS_123"), 0)
    assert page.articles[0]["url"] == "https://mp.weixin.qq.com/s/original-link"


def test_missing_next_cursor_is_not_history_exhaustion():
    client, _ = client_with({"articles": [], "hasMore": 1})
    with pytest.raises(UnexpectedResponse):
        client.history(Account("测试号", "", "MP_WXS_123"), 0)


def test_upstream_credentials_are_not_echoed():
    runner = Mock(return_value=CompletedProcess([], 1, "", "token=SECRET"))
    client = WeReadClient(binary="test", runner=runner)
    with pytest.raises(SessionExpired) as exc:
        client.search("测试")
    assert "SECRET" not in str(exc.value)
