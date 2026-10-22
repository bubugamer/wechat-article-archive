import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from wechat_archive.accounts import Account
from wechat_archive.errors import (
    ArchiveError,
    RateLimited,
    SessionExpired,
    UnexpectedResponse,
    VerificationRequired,
)
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
    with pytest.raises(ArchiveError) as exc:
        client.search("测试")
    assert "SECRET" not in str(exc.value)


def test_start_reuses_a_valid_login_without_showing_qr(monkeypatch):
    client, _ = client_with({"ok": True})
    login = Mock()
    monkeypatch.setattr("wechat_archive.login_ui.qr_login", login)
    client.ensure_login()
    login.assert_not_called()


def test_start_logs_in_once_then_checks_connection(monkeypatch):
    runner = Mock(
        side_effect=[
            CompletedProcess([], 1, "", json.dumps({"error": "no WeRead accounts are configured"})),
            result({"ok": True}),
        ]
    )
    client = WeReadClient(binary="test-client", runner=runner)
    login = Mock(return_value=0)
    monkeypatch.setattr("wechat_archive.login_ui.qr_login", login)
    client.ensure_login(open_browser=False)
    login.assert_called_once_with("test-client", open_browser=False, timeout=300)
    assert runner.call_count == 2


@pytest.mark.parametrize(
    "error,exception",
    [
        ({"error": "verification", "errCode": -2041}, VerificationRequired),
        ({"error": "too many requests", "status": 429}, RateLimited),
        ({"error": "network unavailable"}, ArchiveError),
    ],
)
def test_network_or_verification_does_not_launch_relogin(error, exception, monkeypatch):
    runner = Mock(return_value=CompletedProcess([], 1, "", json.dumps(error)))
    client = WeReadClient(binary="test-client", runner=runner)
    login = Mock()
    monkeypatch.setattr("wechat_archive.login_ui.qr_login", login)
    with pytest.raises(exception):
        client.ensure_login()
    login.assert_not_called()


def test_unattended_mode_never_launches_login(monkeypatch):
    runner = Mock(return_value=CompletedProcess([], 1, "", json.dumps({"status": 401})))
    client = WeReadClient(binary="test-client", runner=runner)
    login = Mock()
    monkeypatch.setattr("wechat_archive.login_ui.qr_login", login)
    with pytest.raises(SessionExpired):
        client.ensure_login(auto=False)
    login.assert_not_called()
