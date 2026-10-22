import json
import stat
from pathlib import Path
from unittest.mock import Mock

from wechat_archive.cli import main
from wechat_archive.errors import SessionExpired


def test_account_name_to_files_through_real_client_subprocess(
    tmp_path, original_html, monkeypatch, capsys
):
    # Run a synthetic upstream executable, then the real CLI -> search -> history -> HTTP
    # parser -> disk -> resume path. The two HTTP pages are publisher-page fixtures.
    binary = tmp_path / "synthetic-weread"
    binary.write_text(
        """#!/usr/bin/env python3
import json,sys
args=sys.argv[1:]
if args[:2]==['search','books']:
    value={'books':[{'bookInfo':{'bookId':'MP_WXS_123','title':'测试公众号'}}]}
elif args[:2]==['public-accounts','articles']:
    value={'articles':[
        {'mpInfo':{'title':'第一篇','doc_url':'https://mp.weixin.qq.com/s/synthetic-one'}},
        {'mpInfo':{'title':'第二篇','doc_url':'https://mp.weixin.qq.com/s/synthetic-two'}}]}
else:
    sys.exit(4)
print(json.dumps(value))
""",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("WEREAD_OMNI_BIN", str(binary))
    get = Mock(return_value=Mock(status_code=200, text=original_html, headers={}))
    monkeypatch.setattr("requests.Session.get", get)
    args = ["account", "测试公众号", "--all", "--interval", "0", "--json", "-o", str(tmp_path)]
    assert main(args) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["archive_complete"] and state["saved_articles"] == 2
    assert len(list(tmp_path.rglob("*.md"))) == 2
    assert get.call_count == 2
    assert Path(state["manifest_path"]).is_file()
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["saved_articles"] == 2
    assert get.call_count == 2  # Both saved originals are reused.


def test_article_command_does_not_save_failed_body(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "requests.Session.get",
        Mock(return_value=Mock(status_code=200, text="<h1>环境异常</h1>", headers={})),
    )
    assert main(["article", "https://mp.weixin.qq.com/s/test", "-o", str(tmp_path)]) == 3
    assert "未取得原文" in capsys.readouterr().err
    assert not list(tmp_path.rglob("*.md"))


def test_no_arguments_starts_login_before_asking_for_name(monkeypatch, capsys):
    client = Mock()
    monkeypatch.setattr("wechat_archive.cli.WeReadClient", Mock(return_value=client))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert main([]) == 2
    client.ensure_login.assert_called_once_with(open_browser=True)
    client.search.assert_not_called()
    assert "未输入公众号名称" in capsys.readouterr().err


def test_json_and_no_login_modes_do_not_open_a_login_window(monkeypatch):
    client = Mock()
    client.search.side_effect = SessionExpired("需要登录")
    monkeypatch.setattr("wechat_archive.cli.WeReadClient", Mock(return_value=client))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert main(["start", "测试公众号", "--json"]) == 2
    assert main(["start", "测试公众号", "--no-login"]) == 2
    client.ensure_login.assert_not_called()


def test_start_reuses_login_and_continues_to_account_archive(monkeypatch, tmp_path):
    from wechat_archive.accounts import Account

    client = Mock()
    client.search.return_value = [Account("测试公众号", "", "MP_WXS_123")]
    monkeypatch.setattr("wechat_archive.cli.WeReadClient", Mock(return_value=client))
    archive = Mock(
        return_value={
            "manifest_path": str(tmp_path / "inventory.json"),
            "history_complete": True,
            "archive_complete": True,
            "discovered_articles": 0,
            "saved_articles": 0,
        }
    )
    monkeypatch.setattr("wechat_archive.cli.archive_account", archive)
    assert main(["start", "测试公众号", "--no-browser"]) == 0
    client.ensure_login.assert_called_once_with(open_browser=False)
    archive.assert_called_once()
