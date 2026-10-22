import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from .accounts import Account, BackendClient
from .article import SHANGHAI
from .errors import ArchiveError, RateLimited, UnexpectedResponse, VerificationRequired
from .http import ArticleClient
from .storage import safe_name, save_article, saved_article_exists, write_json


def archive_account(
    account: Account,
    backend: BackendClient,
    articles: ArticleClient,
    output: Path,
    *,
    max_pages: int = 10000,
    max_articles: int | None = None,
    list_only: bool = False,
    interval: float = 2.0,
    sleeper=time.sleep,
    report=print,
) -> dict:
    identity = hashlib.sha256(account.account_id.encode()).hexdigest()[:10]
    manifest_path = output / "accounts" / f"{safe_name(account.name)}-{identity}.json"
    try:
        state = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {"schema_version": 1, "account": account.to_dict(), "articles": {}}
    except (OSError, ValueError):
        raise ArchiveError("已有归档清单损坏，请先备份并检查该清单文件。") from None
    if not isinstance(state, dict) or not isinstance(state.get("articles"), dict):
        raise ArchiveError("已有归档清单格式不正确，未覆盖原文件。")
    state.update(
        history_complete=False,
        archive_complete=False,
        error=None,
        next_offset=0,
        global_history_complete=False,
        scanned_publish_records=0,
        scope="当前登录会话可见的历史列表；不包含已删除、不可见或平台未返回的文章",
        started_at=datetime.now(SHANGHAI).isoformat(),
    )
    verified_saved = {
        url for url, record in state["articles"].items() if saved_article_exists(record, output)
    }

    def checkpoint():
        state["saved_articles"] = len(verified_saved)
        state["discovered_articles"] = len(state["articles"])
        write_json(manifest_path, state)

    checkpoint()
    seen_pages = set()
    total_records = None
    discovered_this_run = set()
    try:
        # Restart enumeration from the head on each run: new publications shift numeric offsets.
        for page_number in range(max_pages):
            if page_number:
                sleeper(interval)
            page = backend.history(account, state["next_offset"])
            if total_records is None:
                total_records = page.total_records
            elif total_records != page.total_records:
                raise UnexpectedResponse("抓取期间历史总数发生变化，请重跑命令以重新核对完整列表。")
            state["visible_publish_records"] = total_records
            if not page.record_count:
                if not page.is_last:
                    raise UnexpectedResponse("历史列表提前返回空页，未标记为全部完成。")
                state["history_complete"] = True
                break
            signature = tuple(row["url"] for row in page.articles)
            if signature in seen_pages:
                raise UnexpectedResponse("微信重复返回同一历史页，已停止以避免无限抓取。")
            seen_pages.add(signature)
            for row in page.articles:
                url = row["url"]
                discovered_this_run.add(url)
                state["articles"].setdefault(url, {}).update(row)
            previous_offset = state["next_offset"]
            state["next_offset"] = page.next_offset
            state["scanned_publish_records"] += page.record_count
            checkpoint()
            report(
                f"历史列表：已读取 {state['scanned_publish_records']} 条记录，"
                f"本轮发现 {len(discovered_this_run)} 篇文章"
            )
            if page.is_last:
                state["history_complete"] = True
                break
            if page.next_offset is None or page.next_offset <= previous_offset:
                raise UnexpectedResponse("历史列表没有有效的下一页位置，未标记为全部完成。")
        if not state["history_complete"]:
            state["error"] = "达到 --max-pages 上限，历史列表尚未遍历完成。"
        state["current_visible_articles"] = len(discovered_this_run)
        checkpoint()
    except ArchiveError as exc:
        state["error"] = str(exc)
        checkpoint()
        raise

    downloaded = 0
    for url, record in state["articles"].items():
        if list_only:
            break
        if url in verified_saved:
            record.pop("error", None)
            continue
        if max_articles is not None and downloaded >= max_articles:
            break
        if downloaded:
            sleeper(interval)
        try:
            article = articles.fetch(url)
            if article.account and article.account != account.name:
                raise UnexpectedResponse("原文公众号名称与所选账号不一致，未保存到此账号归档。")
            record.update(save_article(article, output))
            verified_saved.add(url)
            record.pop("error", None)
            report(f"已保存：{article.title}")
        except ArchiveError as exc:
            record["error"] = str(exc)
            report(f"未取得原文：{record.get('title') or url}（{exc}）")
            if isinstance(exc, (VerificationRequired, RateLimited)):
                state["error"] = str(exc)
                checkpoint()
                break
        downloaded += 1
        checkpoint()
    state["archive_complete"] = (
        state["history_complete"]
        and state["saved_articles"] == state["discovered_articles"]
        and not list_only
    )
    state["finished_at"] = datetime.now(SHANGHAI).isoformat()
    checkpoint()
    return {**state, "manifest_path": str(manifest_path)}
