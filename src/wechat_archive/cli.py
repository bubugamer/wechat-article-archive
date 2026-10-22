import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .accounts import BackendClient, select_account
from .archive import archive_account
from .auth import default_session_path, load_session, login
from .errors import ArchiveError
from .http import ArticleClient
from .storage import save_article
from .weread import WeReadClient, login_personal


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def nonnegative(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 3600:
        raise argparse.ArgumentTypeError("必须在 0 到 3600 秒之间")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="读取微信原文，按公众号名称归档可见历史文章。")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    article = commands.add_parser("article", help="读取一篇或多篇微信原文，无需登录")
    article.add_argument("urls", nargs="*")
    article.add_argument("--input", type=Path, help="每行一个微信原文链接的 UTF-8 文件")
    article.add_argument("-o", "--output", type=Path, default=Path("output"))
    article.add_argument("--json", action="store_true")
    auth = commands.add_parser("login", help="普通微信扫码登录；可选公众号后台方式")
    auth.add_argument("--provider", choices=["weread", "backend"], default="weread")
    auth.add_argument("--session", type=Path, default=default_session_path())
    auth.add_argument("--no-browser", action="store_true", help="只显示本机扫码页面地址")
    auth.add_argument("--timeout", type=positive, default=300, help="等待扫码的最长秒数")
    auth.add_argument("--qr-output", type=Path, help="临时二维码 PNG，登录结束后自动删除")
    for name, help_text in (
        ("search", "搜索公众号"),
        ("account", "遍历公众号可见历史并下载原文"),
        ("start", "启动：检查登录，必要时显示扫码窗口，再归档公众号"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("name", nargs="?" if name == "start" else None)
        sub.add_argument("--provider", choices=["weread", "backend"], default="weread")
        sub.add_argument("--session", type=Path, default=default_session_path())
        sub.add_argument("--json", action="store_true")
        sub.add_argument(
            "--no-login", action="store_true", help="登录失效时直接报错，不打开扫码窗口"
        )
        sub.add_argument("--no-browser", action="store_true", help="仅显示本机扫码页面地址")
        if name != "search":
            sub.add_argument("--account-id", help="同名公众号的精确身份标识，先用 search 查询")
            sub.add_argument(
                "--all", action="store_true", help="遍历当前来源可见的全部历史（默认行为）"
            )
            sub.add_argument("--max-pages", type=positive, default=10000)
            sub.add_argument("--max-articles", type=positive, help="限制本轮下载数量，其余留待下轮")
            sub.add_argument("--list-only", action="store_true", help="只保存完整历史链接清单")
            sub.add_argument("--interval", type=nonnegative, default=2.0)
            sub.add_argument("-o", "--output", type=Path, default=Path("output"))
    return root


def main(argv: list[str] | None = None) -> int:
    supplied = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(supplied or ["start"])
    try:
        if args.command == "login":
            if args.provider == "weread":
                return login_personal(
                    open_browser=not args.no_browser, timeout=args.timeout, qr_output=args.qr_output
                )
            login(args.session)
            print(f"公众号后台登录状态已保存至本机：{args.session}")
            return 0
        if args.command == "article":
            urls = list(args.urls)
            if args.input:
                urls.extend(
                    line.strip()
                    for line in args.input.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
            if not urls:
                raise ArchiveError("请提供微信原文链接，或使用 --input 指定链接文件。")
            client = ArticleClient()
            results = []
            for url in dict.fromkeys(urls):
                try:
                    article = client.fetch(url)
                    record = save_article(article, args.output)
                    results.append({"url": article.source_url, "title": article.title, **record})
                except ArchiveError as exc:
                    results.append({"url": url, "error": str(exc)})
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            else:
                for result in results:
                    if "error" in result:
                        print(f"未取得原文：{result['error']}", file=sys.stderr)
                    else:
                        print(f"已保存：{args.output / result['files']['md']}")
            return 3 if any("error" in result for result in results) else 0
        backend = (
            WeReadClient()
            if args.provider == "weread"
            else BackendClient(load_session(args.session))
        )
        interactive_login = (
            args.provider == "weread"
            and not args.no_login
            and not args.json
            and (args.command == "start" or sys.stdin.isatty())
        )
        if interactive_login:
            backend.ensure_login(open_browser=not args.no_browser)
        if not args.name:
            if not sys.stdin.isatty():
                raise ArchiveError("请用 wechat-archive start '公众号名称' 指定目标。")
            args.name = input("请输入公众号名称：").strip()
            if not args.name:
                raise ArchiveError("未输入公众号名称，没有开始读取。")
        if not args.json:
            print(f"正在查找公众号：{args.name}…", flush=True)
        candidates = backend.search(args.name)
        if args.command == "search":
            if args.json:
                print(json.dumps([a.to_dict() for a in candidates], ensure_ascii=False, indent=2))
            else:
                for account in candidates:
                    print(f"{account.name}\t{account.alias}\t{account.account_id}")
            return 0
        account = select_account(candidates, args.name, args.account_id)
        state = archive_account(
            account,
            backend,
            ArticleClient(),
            args.output,
            max_pages=args.max_pages,
            max_articles=args.max_articles,
            list_only=args.list_only,
            interval=args.interval,
            report=(lambda _: None) if args.json else print,
        )
        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(f"清单：{state['manifest_path']}")
            print(
                f"当前来源列表已遍历：{'是' if state['history_complete'] else '否'}；"
                f"发现 {state['discovered_articles']} 篇，已保存 {state['saved_articles']} 篇。"
            )
            print("范围仅限当前来源可见历史，不能据此证明覆盖该公众号自创建以来的全部文章。")
        complete = state["history_complete"] if args.list_only else state["archive_complete"]
        return 0 if complete else 3
    except (ArchiveError, OSError) as exc:
        print(f"无法完成：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断；已写入的归档和清单保留。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
