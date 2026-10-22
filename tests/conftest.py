import pytest


@pytest.fixture
def original_html():
    # Synthetic article: no real publisher body, account IDs, cookies, or tokens.
    return """<!doctype html><html><body>
    <h1 id="activity-name">测试文章：嵌套正文</h1><a id="js_name">测试公众号</a>
    <div id="js_content"><p>第一段。<strong>重点内容</strong></p>
      <div><section><p>中间段落。</p>
      <img data-src="https://mmbiz.qpic.cn/test.jpg" /></section></div>
      <p>最后一段，必须完整保留。</p><script>hidden()</script>
    </div><footer>不属于正文的导航</footer>
    <script>var ct = "1791978980"; var biz = "synthetic-biz";
    var author = "测试作者";</script></body></html>"""
