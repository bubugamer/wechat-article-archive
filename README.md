# WeChat Article Archive · 微信原文归档

[![Checks](https://github.com/bubugamer/wechat-article-archive/actions/workflows/checks.yml/badge.svg)](https://github.com/bubugamer/wechat-article-archive/actions/workflows/checks.yml)

给一个微信文章链接，保存微信原页面的完整文字正文；给一个公众号名称，分页发现当前来源可见的历史文章，再逐篇保存原文。支持 Markdown、纯文本和 JSON，保留来源、发布时间、图片位置和失败清单。

**没有公众号后台账号也可以使用：默认通过个人微信扫码登录微信读书来查找公众号与历史列表。** 此路径使用独立的 [weread-omni 0.1.2](https://github.com/teng-lin/weread-omni/tree/v0.1.2) 客户端；本项目负责分页归档、原文获取、去重和完成状态，不读取你的浏览器 Cookie 数据库。

**“全部”的范围必须明确。** 本项目遍历到当前来源的历史列表末页，不承诺覆盖任意公众号自创建以来的每一篇文章。微信读书收录不全、已删除文章、权限、付费预览、验证码及接口变化都会影响覆盖率。后台方式同样只代表该会话可见范围。不会用搜索摘要、转载或登录页填充正文，也不会把截断的运行标成全部成功。

## 安装

单篇原文需要 Python 3.11+；整号默认方式还需要 Node.js 22.13+。当前发布于 GitHub，尚未发布到 PyPI。

```bash
git clone https://github.com/bubugamer/wechat-article-archive.git
cd wechat-article-archive
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Windows 激活命令：`.venv\Scripts\Activate.ps1`。

## 先获取一篇微信原文

```bash
wechat-archive article 'https://mp.weixin.qq.com/s/PUNsXloYHA3-M0QnZ73Lkg' -o output

# 多个链接，或每行一个链接的 UTF-8 文件
wechat-archive article 'https://mp.weixin.qq.com/s/ARTICLE_A' 'https://mp.weixin.qq.com/s/ARTICLE_B'
wechat-archive article --input links.txt --json
```

无需登录。程序直接请求微信原链接，依次尝试移动 Safari、微信客户端标识、桌面浏览器标识，解析 `#js_content`，保留嵌套段落和 `data-src` 图片。只接收微信 HTTPS 文章链接。遇到验证时不会自动解题。

输出包含 `.md`、`.txt`、`.json` 三份文件。图片保留原位置及在线链接；当前版本不下载图片，因此不是完全离线图文包。图片消息中没有文字正文的情况会报告无法提取，不自动识别图片文字。评论、阅读数、视频文件不在正文归档范围内。

## 按公众号名称获取历史文章：无需公众号后台

```bash
# 安装个人微信读书客户端；登录信息只保存在本机
npm install -g weread-omni@0.1.2
wechat-archive login

# 先核对同名账号；没有歧义时 account 可直接用名称
wechat-archive search '国家电投云南国际'
wechat-archive account '国家电投云南国际' --all -o output
```

`login` 会显示微信读书登录二维码，由你自己扫码。需要已开通微信读书的个人账号，不需要运营公众号。程序只搜索、读取列表和原文，不自动关注、取消关注、发布或修改内容。

如果搜不到目标号，不能据此认定这个号没有文章：它可能没有被当前来源收录。程序会说明没有找到，不能无登录地保证获取任意公众号全部历史。

同名公众号必须用搜索结果中的 ID 明确选择：

```bash
wechat-archive account '公众号名称' --account-id MP_WXS_1234567890 --all
```

常用选项：

```bash
# 只遍历并保存链接清单
wechat-archive account '公众号名称' --all --list-only

# 限制本轮下载量，保留其余任务；此轮会返回“未完成”
wechat-archive account '公众号名称' --max-articles 20

# 重新运行同一命令：重新核对历史，只补缺失、损坏或失败的正文
wechat-archive account '公众号名称' --all

# 更慢地读取，避免连续请求
wechat-archive account '公众号名称' --interval 5
```

默认逐页串行读取，页间、文章间至少间隔 2 秒。默认安全页数上限为 10000，可用 `--max-pages` 调整；触及上限会明确报告列表未遍历完成。请勿对同一个输出目录同时运行多个归档进程。

## 可选：微信公众号后台方式

如果你以后有自己的公众号后台登录权限，也可以用后台内置的其他公众号文章列表：目标号无需由你管理。

```bash
pip install '.[login]'
playwright install chromium
wechat-archive login --provider backend
wechat-archive search '公众号名称' --provider backend
wechat-archive account '公众号名称' --provider backend --all
```

扫码登录窗口使用独立的新浏览器会话，不读取现有浏览器配置。凭据写入 `~/.config/wechat-article-archive/session.json`（支持 `XDG_CONFIG_HOME`），权限设为仅当前用户可读写。可通过 `--session` 指定本地文件；不要把该文件发给他人或提交 GitHub。

## 输出与完成状态

```text
output/
  articles/公众号名称/
    日期-标题-链接摘要.md
    日期-标题-链接摘要.txt
    日期-标题-链接摘要.json
  accounts/
    公众号名称-身份摘要.json
```

公众号清单同时记录：

| 字段 | 含义 |
| --- | --- |
| `history_complete` | 本轮是否遍历到当前来源可见列表末页 |
| `archive_complete` | 列表已遍历，且清单中每篇正文都已保存 |
| `global_history_complete` | 始终为 `false`：本工具没有证据证明平台返回了该号自创建以来全部文章 |
| `discovered_articles` / `saved_articles` | 累计发现的原文链接数 / 已核对的完整保存数 |
| `current_visible_articles` | 本轮列表中实际发现的链接数，不包含仅在旧归档中存在的链接 |
| `next_offset` / `error` | 本轮下一页位置 / 中断原因 |
| `articles` | 每篇原文链接、文件位置、正文校验值与失败原因 |

旧文件保留，不会因为新列表不再展示某篇文章就删除。重新运行会从最新一页重新核对，避免新增发布让数字页码偏移后漏掉文章；已经保存且核对无误的正文直接跳过。遇到持续限流或人工验证会停下并保留进度。

退出码：`0` 表示本次请求范围完成（`--list-only` 只要求列表完成）；`2` 表示登录、网络、账号选择或列表异常；`3` 表示部分正文失败或达到数量上限；`130` 表示用户中断。

## 用户用例（User Cases）

| 触发 | 用户操作 | 预期行为 | 歧义或失败处理 |
| --- | --- | --- | --- |
| 想保存一篇文章 | 提供原文链接 | 从微信原页面保存正文、日期和来源 | 验证页、删除页不保存为文章 |
| 没有公众号后台账号 | 个人微信读书扫码后提供公众号名 | 搜索并分页读取可见历史，逐篇获取原文 | 未收录、访问受限或列表结构变化时明确停止 |
| 多个公众号同名 | 运行 `search` 后指定 ID | 归档明确选择的账号 | 不默认选择第一个模糊匹配 |
| 一次发布多篇文章 | 运行整号归档 | 展开发布记录中的每一篇 | 发布批次数与文章数分别统计 |
| 网络或验证中断 | 处理后重跑同一命令 | 保留已保存文件，补抓未完成项 | 持续限流、人工验证不报成末页 |
| 限制本轮读取量 | 设置 `--max-pages` 或 `--max-articles` | 保存已取得结果 | 明确返回未完成，不声称已获取全部 |

## 验证与开发

```bash
pip install -e '.[dev]'
ruff check src tests
ruff format --check src tests
pytest -q
python -m build
```

测试使用人工构造的文章与接口响应，覆盖正文末尾、图片顺序、多篇发布、翻页、登录失效、同名公众号、限流、重复页、损坏文件恢复及不完整状态。GitHub Actions 不使用真实登录状态，也不访问微信。

实际验证情况见 [docs/verification.md](docs/verification.md)。不把模拟流程通过当成第三方平台当前可用的证明。

## 方法、来源与边界

- 单篇抓取从一次真实微信原文读取整理而来，正文使用 HTML 解析器提取，避免用正则在第一个嵌套 `</div>` 处截断。
- 个人微信读书方式委托 [weread-omni](https://github.com/teng-lin/weread-omni/tree/v0.1.2) 处理登录和设备请求；本项目读取其 JSON 输出。源码通过子进程调用该客户端，不复制其实现；其许可证及外部服务限制独立适用。
- 后台返回格式参照 [可追溯的接口观察记录](https://github.com/Alex-giao/wechat-mp-article-list/blob/main/references/backend-workflow.md) 独立实现。`publish_page` 和 `publish_info` 分别解析，发布记录展开后再逐篇读取。
- 两种历史来源都依赖非公开接口，存在变更、权限和收录限制。请只读取你有权访问的内容，保留原作者与来源信息。代码按 MIT 开源，文章著作权仍归原权利人。

技术说明见 [docs/design.md](docs/design.md)。
