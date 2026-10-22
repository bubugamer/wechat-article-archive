import json
from unittest.mock import Mock

import pytest

from wechat_archive.accounts import Account, HistoryPage
from wechat_archive.archive import archive_account
from wechat_archive.article import parse_article
from wechat_archive.errors import RateLimited, UnexpectedResponse, VerificationRequired

ACCOUNT = Account("测试公众号", "synthetic", "synthetic-id")


def row(number):
    return {"url": f"https://mp.weixin.qq.com/s/synthetic-{number}", "title": str(number)}


class History:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def history(self, account, begin):
        self.calls.append(begin)
        page = self.pages[begin]
        if isinstance(page, Exception):
            raise page
        return page


def run(tmp_path, original_html, pages=None, client=None, **options):
    history = History(
        pages
        or {
            0: HistoryPage([row(1), row(2)], 1, 2, 1, False),
            1: HistoryPage([row(3)], 1, 2, 2, True),
        }
    )
    client = client or Mock(fetch=lambda url: parse_article(original_html, url))
    state = archive_account(
        ACCOUNT, history, client, tmp_path, sleeper=lambda _: None, report=lambda _: None, **options
    )
    return state, history, client


def test_full_paginated_history_downloads_all_articles(tmp_path, original_html):
    state, history, _ = run(tmp_path, original_html)
    assert history.calls == [0, 1]
    assert state["history_complete"] and state["archive_complete"]
    assert state["discovered_articles"] == state["saved_articles"] == 3
    assert state["global_history_complete"] is False
    assert len(list(tmp_path.rglob("*.md"))) == 3


def test_rerun_repairs_missing_file_and_does_not_refetch_saved_articles(tmp_path, original_html):
    state, _, _ = run(tmp_path, original_html)
    missing = state["articles"][row(2)["url"]]["files"]["md"]
    (tmp_path / missing).unlink()
    client = Mock()
    client.fetch.side_effect = lambda url: parse_article(original_html, url)
    state, history, _ = run(tmp_path, original_html, client=client)
    assert history.calls[0] == 0  # New articles can shift offsets since the previous run.
    client.fetch.assert_called_once_with(row(2)["url"])
    assert state["archive_complete"]


@pytest.mark.parametrize("options", [{"max_pages": 1}, {"max_articles": 1}, {"list_only": True}])
def test_limits_never_report_full_body_archive(tmp_path, original_html, options):
    state, _, _ = run(tmp_path, original_html, **options)
    assert not state["archive_complete"]
    if options.get("max_pages"):
        assert not state["history_complete"]


def test_rate_limit_keeps_inventory_and_incomplete_status(tmp_path, original_html):
    with pytest.raises(RateLimited):
        run(
            tmp_path,
            original_html,
            pages={
                0: HistoryPage([row(1)], 1, 2, 1, False),
                1: RateLimited("暂停"),
            },
        )
    state = json.loads(next((tmp_path / "accounts").glob("*.json")).read_text())
    assert not state["history_complete"] and not state["archive_complete"]
    assert state["next_offset"] == 1 and len(state["articles"]) == 1


def test_changed_total_is_not_reported_complete(tmp_path, original_html):
    with pytest.raises(UnexpectedResponse, match="总数发生变化"):
        run(
            tmp_path,
            original_html,
            pages={
                0: HistoryPage([row(1)], 1, 2, 1, False),
                1: HistoryPage([row(2)], 1, 3, 2, False),
            },
        )


def test_repeated_page_is_not_reported_complete(tmp_path, original_html):
    with pytest.raises(UnexpectedResponse, match="重复返回"):
        run(
            tmp_path,
            original_html,
            pages={
                0: HistoryPage([row(1)], 1, 3, 1, False),
                1: HistoryPage([row(1)], 1, 3, 2, False),
            },
        )


def test_verification_stops_batch_and_rerun_recovers(tmp_path, original_html):
    client = Mock()
    client.fetch.side_effect = VerificationRequired("需要验证")
    state, _, _ = run(tmp_path, original_html, client=client)
    assert client.fetch.call_count == 1
    assert state["history_complete"] and not state["archive_complete"]
    assert state["saved_articles"] == 0
    state, _, _ = run(tmp_path, original_html)
    assert state["archive_complete"] and state["saved_articles"] == 3
