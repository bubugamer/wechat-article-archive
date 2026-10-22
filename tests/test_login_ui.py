import json
import shutil

import pytest
import requests

from wechat_archive.errors import ArchiveError
from wechat_archive.login_ui import LoginWindow, qr_login


def test_qr_window_renders_and_private_routes_only_expose_status():
    with LoginWindow() as window:
        assert window.server.server_address[0] == "127.0.0.1"
        page = requests.get(window.url, timeout=2)
        assert page.status_code == 200
        assert "用手机微信扫码登录" in page.text
        assert "Cache-Control" in page.headers and page.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert requests.get(window.origin + "/", timeout=2).status_code == 404
        window.set_qr("https://open.weixin.qq.com/connect/confirm?uuid=synthetic-test")
        image = requests.get(window.url + "qr.png", timeout=2)
        assert image.content.startswith(b"\x89PNG")
        status = requests.get(window.url + "status", timeout=2).json()
        assert status["has_qr"]
        assert "uuid" not in json.dumps(status) and "token" not in page.text
        window.update("done", "登录成功")
        assert requests.get(window.url + "qr.png", timeout=2).status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/connect/confirm?uuid=x",
        "https://open.weixin.qq.com.evil.test/connect/confirm?uuid=x",
        "https://open.weixin.qq.com/connect/confirm",
        "http://open.weixin.qq.com/connect/confirm?uuid=x",
    ],
)
def test_non_wechat_authorization_is_rejected(url):
    with LoginWindow() as window, pytest.raises(ArchiveError):
        window.set_qr(url)


def test_cancel_requires_same_origin_and_clears_qr():
    with LoginWindow() as window:
        window.set_qr("https://open.weixin.qq.com/connect/confirm?uuid=synthetic-test")
        assert requests.post(window.url + "cancel", timeout=2).status_code == 403
        assert not window.cancelled.is_set()
        response = requests.post(
            window.url + "cancel", headers={"Origin": window.origin}, timeout=2
        )
        assert response.status_code == 200 and window.cancelled.is_set()
        assert not window.png


@pytest.fixture
def synthetic_sdk(tmp_path):
    cli = tmp_path / "cli.js"
    (tmp_path / "package.json").write_text('{"type":"module"}')
    (tmp_path / "index.js").write_text("export class AccountManager {}")
    cli.write_text("""export async function runAccountCli(argv, dependencies) {
      await dependencies.renderQr('https://open.weixin.qq.com/connect/confirm?uuid=synthetic-test');
      dependencies.stdout.write(JSON.stringify({accessToken:'NEVER_RELAY_TOKEN'}));
      dependencies.stderr.write('scanned');
      return 0;
    }""")
    return cli


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for article-only users")
def test_qr_bridge_completes_without_relaying_credentials(synthetic_sdk, tmp_path, capsys):
    output = tmp_path / "temporary-qr.png"
    assert qr_login(str(synthetic_sdk), open_browser=False, timeout=5, qr_output=output) == 0
    messages = capsys.readouterr().out
    assert "二维码已就绪" in messages and "登录成功" in messages
    assert "NEVER_RELAY_TOKEN" not in messages and "accessToken" not in messages
    assert not output.exists()


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for article-only users")
def test_expired_login_cannot_continue_to_archive(synthetic_sdk, capsys):
    synthetic_sdk.write_text("""export async function runAccountCli(argv, dependencies) {
      dependencies.stderr.write(JSON.stringify({error:'QR expired'})); return 1;
    }""")
    with pytest.raises(ArchiveError, match="过期"):
        qr_login(str(synthetic_sdk), open_browser=False, timeout=5)
    assert "登录成功" not in capsys.readouterr().out
