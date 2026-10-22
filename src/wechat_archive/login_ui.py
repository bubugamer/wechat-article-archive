"""A temporary loopback-only QR window. No credential is exposed to the browser."""

import io
import json
import queue
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import qrcode

from .errors import ArchiveError

PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>微信原文归档 · 扫码登录</title>
<style nonce="NONCE">
*{box-sizing:border-box}body{margin:0;background:#f5f6f5;color:#18251e;font-family:system-ui,
-apple-system,sans-serif;display:grid;min-height:100vh;place-items:center;padding:24px}
main{max-width:480px;width:100%;padding:36px;background:white;border:1px solid #e4e9e5;
border-radius:20px;text-align:center;box-shadow:0 16px 48px #1633230b}
.label{font-size:13px;color:#52725e;letter-spacing:2px}h1{font-size:26px;margin:14px 0}
p{line-height:1.7;color:#617066}#qr{display:none;width:260px;height:260px;margin:20px auto}
#status{font-weight:600;color:#207143;min-height:28px}.note{font-size:13px}
button{background:white;color:#45634f;border:1px solid #cddacf;border-radius:9px;
padding:10px 20px;cursor:pointer}button:disabled{opacity:.5;cursor:default}
</style><main><div class="label">微信原文归档</div><h1>用手机微信扫码登录</h1>
<p>授权微信读书后，程序将继续读取公众号文章。<br>不需要公众号后台账号。</p>
<img id="qr" alt="微信读书登录二维码"><p id="status" role="status">正在获取二维码…</p>
<p class="note">请在手机上核对授权页面并确认。<br>登录信息只保存在这台电脑上。</p>
<button id="cancel">取消登录</button></main>
<script nonce="NONCE">
let finished=false; const base=location.pathname;
const status=document.getElementById('status'), qr=document.getElementById('qr');
const cancel=document.getElementById('cancel');
async function poll(){
 try{
  const r=await fetch(base+'status',{cache:'no-store'});if(!r.ok)throw Error();
  const s=await r.json();status.textContent=s.message;
  if(s.has_qr && !qr.src){qr.src=base+'qr.png';qr.style.display='block'}
  if(['done','error','cancelled','expired'].includes(s.phase)){
   finished=true;cancel.disabled=true;qr.style.display='none';
  }
 }catch{status.textContent='登录窗口已结束。请返回程序查看结果。';finished=true;cancel.disabled=true}
 if(!finished)setTimeout(poll,750);
}
cancel.onclick=async()=>{await fetch(base+'cancel',{method:'POST'});await poll()};poll();
</script></html>"""


class LoginWindow:
    def __init__(self):
        self.path = "/" + secrets.token_urlsafe(24) + "/"
        self.nonce = secrets.token_urlsafe(18)
        self.phase = "waiting"
        self.message = "正在获取二维码…"
        self.png = b""
        self.cancelled = threading.Event()
        window = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status: int, content_type: str, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    f"script-src 'nonce-{window.nonce}'; "
                    f"style-src 'nonce-{window.nonce}'; img-src 'self'; "
                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                )
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == window.path:
                    self.send(
                        200,
                        "text/html; charset=utf-8",
                        PAGE.replace("NONCE", window.nonce).encode(),
                    )
                elif self.path == window.path + "status":
                    body = json.dumps(
                        {
                            "phase": window.phase,
                            "message": window.message,
                            "has_qr": bool(window.png),
                        },
                        ensure_ascii=False,
                    ).encode()
                    self.send(200, "application/json; charset=utf-8", body)
                elif self.path == window.path + "qr.png" and window.png:
                    self.send(200, "image/png", window.png)
                else:
                    self.send(404, "text/plain", b"Not found")

            def do_POST(self):
                if self.path != window.path + "cancel":
                    self.send(404, "text/plain", b"Not found")
                elif self.headers.get("Origin") != window.origin:
                    self.send(403, "text/plain", b"Forbidden")
                else:
                    window.cancelled.set()
                    window.update("cancelled", "已取消登录。")
                    self.send(200, "application/json", b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.url = self.origin + self.path
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.png = b""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def update(self, phase: str, message: str):
        self.phase, self.message = phase, message
        if phase in ("done", "error", "cancelled", "expired"):
            self.png = b""

    def set_qr(self, url: str):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "open.weixin.qq.com"
            or parsed.path != "/connect/confirm"
            or not parse_qs(parsed.query).get("uuid")
        ):
            raise ArchiveError("登录服务返回了非微信授权地址，已停止。")
        stream = io.BytesIO()
        qrcode.make(url).save(stream, format="PNG")
        self.png = stream.getvalue()
        self.update("waiting", "请用手机微信扫码，并在手机上确认。")


def sdk_cli_path(binary: str) -> Path:
    real = Path(binary).resolve()
    candidates = [
        real,
        real.parent / "node_modules/weread-omni/dist/cli.js",
        real.parent.parent / "lib/node_modules/weread-omni/dist/cli.js",
    ]
    for candidate in candidates:
        if candidate.name == "cli.js" and (candidate.parent / "index.js").is_file():
            return candidate
    npm = shutil.which("npm")
    if npm:
        try:
            root = subprocess.run(
                [npm, "root", "-g"], capture_output=True, text=True, timeout=15, check=True
            ).stdout.strip()
            candidate = Path(root) / "weread-omni/dist/cli.js"
            if candidate.is_file():
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass
    raise ArchiveError("找不到微信读书登录组件，请重新安装 weread-omni@0.1.2。")


def qr_login(binary: str, *, open_browser=True, timeout=300, qr_output: Path | None = None) -> int:
    node = shutil.which("node")
    if not node:
        raise ArchiveError("扫码登录需要 Node.js 22.13 或更新版本。")
    module = sdk_cli_path(binary)
    bridge = Path(__file__).with_name("login_bridge.mjs")
    events = queue.Queue()
    with LoginWindow() as window:
        print(f"扫码登录页面：{window.url}", flush=True)
        if open_browser:
            webbrowser.open(window.url)
        process = subprocess.Popen(
            [node, str(bridge), str(module)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

        def read_events():
            for line in process.stdout:
                try:
                    events.put(json.loads(line))
                except ValueError:
                    pass
            events.put({"event": "eof"})

        thread = threading.Thread(target=read_events, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if window.cancelled.is_set():
                    raise ArchiveError("已取消登录，没有继续读取公众号。")
                try:
                    event = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                kind = event.get("event")
                if kind == "qr":
                    window.set_qr(event.get("url", ""))
                    if qr_output:
                        qr_output.parent.mkdir(parents=True, exist_ok=True)
                        qr_output.write_bytes(window.png)
                        qr_output.chmod(0o600)
                    print("二维码已就绪，请用手机微信扫码，并在手机上确认。", flush=True)
                elif kind == "status":
                    if event.get("status") == "scanned":
                        window.update("scanned", "已扫码，请在手机微信上确认授权。")
                        print("已扫码，等待手机确认。", flush=True)
                    elif event.get("status") == "confirmed":
                        window.update("confirmed", "已确认，正在保存本机登录状态…")
                elif kind == "done" and event.get("ok") is True:
                    window.update("done", "登录成功，请返回程序。")
                    print("登录成功，登录信息已保存在本机。", flush=True)
                    time.sleep(1)
                    return 0
                elif kind in ("error", "eof", "done"):
                    reasons = {
                        "expired": "二维码已过期，请重新启动登录。",
                        "declined": "手机端取消了授权，未继续读取公众号。",
                        "network": "无法连接微信登录服务，请检查网络后重试。",
                    }
                    message = reasons.get(event.get("reason"), "微信授权未完成，请重新扫码登录。")
                    window.update("error", message)
                    raise ArchiveError(message)
            window.update("expired", "等待扫码超时，请重新启动登录。")
            raise ArchiveError("等待扫码超时，没有继续读取公众号。")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdout.close()
            thread.join(timeout=2)
            if qr_output:
                qr_output.unlink(missing_ok=True)
