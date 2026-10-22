import json
from unittest.mock import Mock

import pytest

from wechat_archive.accounts import Account, BackendClient, parse_history, select_account
from wechat_archive.auth import load_session, save_session
from wechat_archive.errors import (
    AmbiguousAccount,
    RateLimited,
    SessionExpired,
    UnexpectedResponse,
)


def envelope(records, total=1):
    return {
        "publish_page": json.dumps(
            {
                "total_count": total,
                "publish_list": [
                    {"publish_info": json.dumps({"appmsgex": entries})} for entries in records
                ],
            }
        )
    }


def test_each_multi_article_publication_is_fully_expanded():
    rows = [
        {"title": str(i), "link": f"https://mp.weixin.qq.com/s/synthetic-{i}"} for i in range(3)
    ]
    page = parse_history(envelope([rows[:2], rows[2:]], 2))
    assert page.record_count == 2 and page.total_records == 2
    assert len(page.articles) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"publish_page": "broken"},
        {"publish_page": {"total_count": 1, "publish_list": [{}]}},
        envelope([[{"title": "missing original link"}]]),
        {"publish_page": {"total_count": 1, "publish_list": [{"publish_info": {"appmsgex": []}}]}},
    ],
)
def test_malformed_history_does_not_silently_skip(payload):
    with pytest.raises(UnexpectedResponse):
        parse_history(payload)


def test_account_resolution_never_chooses_first_fuzzy_result():
    a = Account("测试号", "test-account", "one")
    b = Account("测试号", "another-account", "two")
    with pytest.raises(AmbiguousAccount):
        select_account([a, b], "测试号")
    assert select_account([a, b], "测试号", "two") == b
    assert select_account([a, b], "test-account") == a
    with pytest.raises(AmbiguousAccount):
        select_account([a], "测试")


def backend(retries=3):
    return BackendClient(
        {
            "token": "123",
            "cookies": [
                {"name": "test-cookie", "value": "synthetic", "domain": "mp.weixin.qq.com"}
            ],
        },
        retries=retries,
        sleeper=Mock(),
    )


def reply(ret=0, **data):
    return Mock(status_code=200, json=lambda: {"base_resp": {"ret": ret}, **data})


def test_rate_limit_retries_same_page_then_succeeds():
    client = backend()
    client.session.get = Mock(side_effect=[reply(200013), reply(0, **envelope([], 0))])
    page = client.history(Account("测试号", "", "account"), 0)
    assert page.is_last
    assert client.session.get.call_count == 2
    assert client.session.get.call_args_list[0].kwargs["params"]["begin"] == 0
    assert client.session.get.call_args_list[1].kwargs["params"]["begin"] == 0
    client.sleep.assert_called_once_with(5)


def test_persistent_throttling_fails_instead_of_returning_empty_page():
    client = backend(retries=1)
    client.session.get = Mock(return_value=reply(200013))
    with pytest.raises(RateLimited):
        client.history(Account("测试号", "", "id"), 5)


def test_expired_session_does_not_report_zero_articles():
    client = backend()
    client.session.get = Mock(return_value=reply(200003))
    with pytest.raises(SessionExpired):
        client.search("测试号")


def test_session_is_private_and_only_local(tmp_path):
    path = tmp_path / "credentials.json"
    save_session(path, "123", [{"name": "test", "value": "synthetic"}])
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_session(path)["token"] == "123"
