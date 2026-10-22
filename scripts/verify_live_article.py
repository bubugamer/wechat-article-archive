"""Small opt-in smoke test. Reads one public original; writes only to ignored output/."""

import json
from pathlib import Path

from wechat_archive.http import ArticleClient
from wechat_archive.storage import save_article, saved_article_exists

url = "https://mp.weixin.qq.com/s/PUNsXloYHA3-M0QnZ73Lkg"
article = ArticleClient().fetch(url)
assert article.title == "国家电投云南国际富源西风电场五期项目举行开工仪式"
assert article.account == "国家电投云南国际"
assert article.published_at.startswith("2026-10-14T19:56:")
assert "总投资超过7亿元" in article.text
assert "2026年第68期" in article.text
assert "沈悦秋" in article.text and "刘瑷童" in article.text
assert len(article.images) >= 2
output = Path("output/live-check")
record = save_article(article, output)
assert saved_article_exists(record, output)
print(
    json.dumps(
        {
            "result": "passed",
            "title": article.title,
            "text_characters": len(article.text),
            "images": len(article.images),
            "source": article.source_url,
        },
        ensure_ascii=False,
        indent=2,
    )
)
