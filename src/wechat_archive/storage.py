import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .article import Article
from .urls import article_key


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip(" .")[:70]
    while len(value.encode("utf-8")) > 180:
        value = value[:-1]
    return value or "article"


def save_article(article: Article, output: Path) -> dict:
    directory = output / "articles" / safe_name(article.account or "unknown-account")
    stem = (
        f"{article.published_at[:10] or 'undated'}-{safe_name(article.title)}-"
        f"{article_key(article.source_url)}"
    )
    path = directory / stem
    metadata = (
        f"# {article.title}\n\n"
        f"- 原文链接：{article.source_url}\n"
        f"- 公众号：{article.account}\n"
        f"- 作者：{article.author or '原文未标注'}\n"
        f"- 发布时间：{article.published_at or '原文未标注'}\n"
        f"- 获取时间：{article.fetched_at}\n"
        "- 内容来源：微信原始页面正文\n\n---\n\n"
    )
    files = {}
    for extension, content in (
        ("md", metadata + article.markdown + "\n"),
        ("txt", article.text + "\n"),
        ("json", json.dumps(article.to_dict(), ensure_ascii=False, indent=2) + "\n"),
    ):
        destination = path.with_name(path.name + "." + extension)
        atomic_text(destination, content)
        files[extension] = str(destination.relative_to(output))
    return {"files": files, "content_sha256": article.content_sha256}


def saved_article_exists(record: dict, output: Path) -> bool:
    files = record.get("files", {})
    if set(files) != {"md", "txt", "json"}:
        return False
    root = output.resolve()
    for name in files.values():
        if not isinstance(name, str):
            return False
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return False
    try:
        data = json.loads((root / files["json"]).read_text(encoding="utf-8"))
        saved_markdown = (root / files["md"]).read_text(encoding="utf-8")
        saved_text = (root / files["txt"]).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    markdown = data.get("markdown")
    text = data.get("text")
    if not isinstance(markdown, str) or not isinstance(text, str):
        return False
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    return (
        digest == data.get("content_sha256") == record.get("content_sha256")
        and saved_markdown.endswith(markdown + "\n")
        and saved_text == text + "\n"
    )
