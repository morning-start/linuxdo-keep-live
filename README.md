# linuxdo-keep-live

Linux.do 论坛自动浏览助手 —— 参考 [linuxdosss](https://github.com/icysaintdx/linuxdosss) 项目移植，**浏览器引擎由 DrissionPage 切换为 [CloakBrowser](https://cloakbrowser.dev/)**（Playwright drop-in 隐身 Chromium）。

自动浏览多个板块、点击话题链接（确保「浏览话题」计数）、深度爬楼精确追踪阅读进度，用于保持论坛账号活跃、提升信任等级。

## 为什么换 CloakBrowser

|            | linuxdosss（DrissionPage）                              | linuxdo-keep-live（CloakBrowser）                                       |
| ---------- | ------------------------------------------------------- | ----------------------------------------------------------------------- |
| 引擎       | 用户本机安装的 Chrome                                   | 定制构建的隐身 Chromium（~200MB，自动下载）                             |
| 反检测     | `--disable-blink-features=AutomationControlled` 单 flag | 87 项 C++ 源码级指纹补丁（Canvas/WebGL/音频/字体/GPU/屏幕/UA/CDP）      |
| 反检测层级 | 配置层                                                  | 源码层 + 驱动层双重（`humanize=True` 贝塞尔鼠标、逐字符键盘、拟人滚动） |
| API        | DrissionPage 私有 API                                   | 标准 Playwright API，drop-in 替换                                       |
| 登录态保持 | `set_user_data_path` 持久化                             | `launch_persistent_context` 持久化 profile                              |

> CloakBrowser 官方测试：reCAPTCHA v3 0.9（人类水平）、Cloudflare Turnstile 通过、FingerprintJS / BrowserScan 通过、`navigator.webdriver=false`、TLS 指纹与真实 Chrome 一致。

## 安装

需要 Python ≥ 3.12 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync                      # 安装 cloakbrowser 及依赖
uv sync --extra gui          # 额外安装 GUI 系统托盘支持（pystray + Pillow，可选）
```

首次运行会自动下载浏览器内核（约 200MB，缓存到 `~/.cloakbrowser`）。

> 免费版即可使用最新内核：`python -m cloakbrowser login`（GitHub 登录免费获取 key）或访问 <https://cloakbrowser.dev/free>；
> 也可设置环境变量 `CLOAKBROWSER_LICENSE_KEY`。无 key 时回退到旧的免费二进制。

## 使用

### GUI 版（默认）

```bash
uv run main.py
```

1. 点击「开始」→ 自动打开浏览器
2. 在浏览器中完成登录（程序自动检测，无需其他操作）
3. 登录成功后自动开始浏览 / 爬楼 / 点赞 / 回帖

界面功能：用户信息与等级、升级进度追踪面板（指标/初始值/当前值/目标值/本次+）、运行模式（无尽 / 帖子数量 / 时间限制）、浏览模式（深度爬楼 / 快速浏览）、板块勾选、点赞率 / 回复率 / 等待时间、实时倒计时、运行日志、本次统计、系统托盘（最小化到托盘，悬停显示统计）。

### 无头命令行版（服务器 / Actions / Docker）

```bash
# 命令行参数
uv run main.py cli -u 用户名 -p 密码

# 指定参数（--target：纯数字=帖子数，带单位=时长）
uv run main.py cli -u 用户名 -p 密码 --target 50 --like-rate 20
uv run main.py cli -u 用户名 -p 密码 --target 1h

# 使用代理
uv run main.py cli -u 用户名 -p 密码 --proxy 127.0.0.1:7897

# 环境变量方式
export LINUXDO_USERNAME="用户名"
export LINUXDO_PASSWORD="密码"
export LINUXDO_PROXY="127.0.0.1:7897"
export LINUXDO_TARGET="30min"
uv run main.py cli
```

无头版通过持久化 profile 保持登录态：首次输入账号密码登录，之后复用 Cookie，失效会自动重新登录。

**运行目标 `--target`**（环境变量 `LINUXDO_TARGET`）：一个参数同时表达两种浏览方式——

| 输入 | 含义 |
| --- | --- |
| `30` / `50帖` | 浏览 30 / 50 个帖子后停止 |
| `30min` / `45分钟` | 运行 30 / 45 分钟后停止 |
| `1h` / `1.5h` / `2小时` | 运行 1 / 1.5 / 2 小时后停止 |
| `90s` | 运行 90 秒 |
| 留空 / 识别不了 | 默认 **30 分钟** |

规则：**带时间单位 = 按时长，纯数字 = 按帖子数量**。兼容旧参数名 `--topics`（等价 `--target`）。

| 参数              | 默认值                      | 说明                                                |
| ----------------- | --------------------------- | --------------------------------------------------- |
| `-u, --username`  | 环境变量 `LINUXDO_USERNAME` | 用户名                                              |
| `-p, --password`  | 环境变量 `LINUXDO_PASSWORD` | 密码                                                |
| `--proxy`         | 环境变量 `LINUXDO_PROXY`    | 代理地址，如 `127.0.0.1:7897`（自动补全 `http://`） |
| `--target`        | 30min                       | 运行目标：纯数字=帖子数，带单位=时长（见上表）      |
| `--like-rate`     | 30                          | 点赞概率（0-100）                                   |
| `--browse-mode`   | deep                        | `deep`=深度爬楼，`quick`=快速浏览（3-5层换帖）      |
| `--no-headless`   | 关闭                        | 显示浏览器窗口（调试/首次登录用）                   |
| `--no-humanize`   | 关闭                        | 禁用拟人行为（默认开启）                            |
| `--load-images`   | 关闭                        | **加载**图片（默认禁用图片以降低流量和首屏时间，弱网推荐） |
| `--user-data-dir` | ./browser_data              | 用户数据目录                                        |
| `--debug`         | 关闭                        | 调试日志                                            |

### Docker / 服务器常驻版（随机调度）

```bash
# 启动调度器：每天随机 2 个时间点（7:00-23:00 之间，±15 分钟抖动）各运行一次
python main.py docker -u 用户名 -p 密码

# 自定义频率与目标（--target 同 CLI：纯数字=帖子数，带单位=时长）
python main.py docker -u 用户名 -p 密码 --runs-per-day 3 --target 45min

# 每次随机 15-40 帖（不设 target 时的默认行为）
python main.py docker -u 用户名 -p 密码 --runs-per-day 3 --topics-min 15 --topics-max 40

# 只运行一次（调试用）
python main.py docker -u 用户名 -p 密码 --once
```

环境变量：`LINUXDO_USERNAME` / `LINUXDO_PASSWORD` / `LINUXDO_PROXY` / `LINUXDO_TARGET`（同 `--target`，未设置时每次随机 `TOPICS_MIN`-`TOPICS_MAX` 帖）/ `LIKE_RATE` / `RUNS_PER_DAY` / `TOPICS_MIN` / `TOPICS_MAX` / `CHROME_USER_DATA` / `RUN_ON_START`（首次启动是否立即运行，默认 true）/ `DEBUG`。

每次任务浏览随机数量的帖子（默认 15-40），配合随机时间点，最大程度模拟真人使用习惯。

### GitHub Actions 定时版（云端运行）

仓库自带 [`.github/workflows/run-schedule.yml`](.github/workflows/run-schedule.yml)：在 GitHub 的服务器上定时/手动运行命令行版，本机无需开机。默认跑在 **`windows-latest`** 上（原因见下方风控提示——Linux runner 的指纹与 CloakBrowser 的 Windows 平台声明必然矛盾，会被 Cloudflare 卡死）。

```bash
# 1. Fork 本仓库并设为私有（Settings -> Danger Zone -> Make private）
# 2. 添加 Secrets（Settings -> Secrets and variables -> Actions）：
#      LINUXDO_USERNAME     用户名（必需）
#      LINUXDO_PASSWORD     密码（必需）
#      CLASH_SUB_CONTENT    订阅内容（推荐，见下方风控提示；不填 = 直连）
#      CLASH_SUB            订阅链接（备选，仅当机场不拦 CI 的 IP 时可用）
#      LINUXDO_PROXY        代理地址（可选，以上两个都不配时用）
#      CLOAKBROWSER_LICENSE_KEY  CloakBrowser key（可选，免费获取见上文）
# 3. Actions 页启用 workflows，然后 Run Schedule -> Run workflow 手动触发；
#    「运行目标」填纯数字 = 浏览 N 帖（如 30），带单位 = 时长（如 30min / 1h）；
#    定时触发默认每天 UTC 1:00（北京时间 9:00），每次跑 30min，改 cron 在 yml 里调
```

准备订阅内容 Secret（一行命令，自动裁掉无关配置并复制到剪贴板）：

```bash
python prepare_sub_secret.py "https://你的订阅链接"   # 或直接传 Verge profiles 目录下的 .yaml
# 产物 sub_secret_content.txt（~20KB，避开 Secret 48KB 上限）→ 网页粘贴到 CLASH_SUB_CONTENT
```

工作流细节：

- CloakBrowser 内核（~200MB）自动下载并用 Actions Cache 缓存，第二次起不再下载
- 依赖用 `uv sync --frozen`（uv.lock 锁定版本），CI 上走官方 PyPI 源
- 手动触发参数：运行目标 `target`（同 CLI `--target` 规则）、点赞概率、浏览模式
- 浏览 0 个帖子时 CLI 退出码为 1，该次运行标记失败（邮件通知可在 Watch -> Custom 里设置）
- 同一时间只跑一个任务：上次未结束时新触发自动排队，不会并发登录同一账号
- 注意 `timeout-minutes: 60`：`--target` 设为超过 1 小时的时长会被强制截断
- 登录失败自动重试 3 次，并在 `browser_data/debug/` 留下截图 + 页面快照（失败时作为 artifact 上传，可下载排查）

**风控提示（两道坎）**：GitHub Actions 的出口 IP 是数据中心共享段，会先后遇到两个坎：

1. **HTTP 429 限流**：linux.do 直接拒绝，登录页不渲染。→ 已由 Clash 订阅解决（见下），日志里 `走代理: mihomo` + 真实出口 IP 可核对
2. **Cloudflare Turnstile 托管挑战**：页面卡在 `Just a moment...`，截图是转圈的 `Verifying...`。这是**自动验证没有完成**，不是"过了又被拦"——`cf_clearance` 从未签发

本项目针对第 2 坎已做的（都在代码/工作流里，无需你配置）：

- **CI 跑在 `windows-latest` 上**：CloakBrowser 在 Linux/Windows 都会加 `--fingerprint-platform=windows`（它只在 macOS 上不伪装平台，源码注释写明伪装会造成"字体/GPU 可检测矛盾"）。Linux runner 声称 Windows 却没有 Windows 字体/真实 GPU/UTC 时区/Linux 网络栈，Turnstile 会一直停在 `Verifying…`；Windows runner 上这些声明是**真的**，与本机同类
- 有头模式运行（无头模式 CF 直接拦）。Windows runner 自带桌面会话，无需 Xvfb；若改回 `ubuntu-latest`，workflow 会自动装 Xvfb 并有头跑在虚拟显示上
- 遇到挑战页**静默等待、绝不刷新**（刷新会重置托管挑战进度）
- 判定"已通过"要求**正向内容证据且连续两次稳定**——只看"没有挑战特征"会在 Turnstile 跳转的一瞬间误判成通过
- **登录阶段不挂任何请求拦截**：`ctx.route("**/*")` 会把 `challenges.cloudflare.com` 的请求也改写重发，足以让挑战永远转圈；图片屏蔽改到登录成功后再启用
- 走代理时用 `--fingerprint-webrtc-ip` 把 **WebRTC 伪装成代理出口 IP**，避免 HTTP 走节点 IP、WebRTC 却报出 runner 真实 IP 这种自证代理的组合
- **换节点后重建浏览器**并清 cookie：`cf_clearance` 与签发它的 IP 强绑定，留着旧 IP 的 cookie 去新 IP 只会再触发挑战
- 卡挑战时自动轮换出口节点，且**跨列表分散取样**（订阅里节点按地区成组，连续取 6 个会全落在同一批机房）
- **缓存浏览器 profile**（`browser_data`）：登录态与已通过的 `cf_clearance` 跨运行累积。每次全新 profile 等于每次从零开始挣信誉

> 实测记录：在 Linux runner 上，跨保加利亚 / 爱尔兰(AWS) / 法国 / 德国(Hetzner) / 美国(Zenlayer) 等 6 个不同机房 ASN 全部卡在同一个 `Verifying…`——说明**换节点解决不了环境自洽性问题**。

仍然卡住时，只有两个变量在代码之外，按性价比排序：

1. **配 `CLOAKBROWSER_LICENSE_KEY` Secret**（免费：`python -m cloakbrowser login` 或 <https://cloakbrowser.dev/free>）启用最新内核。免费内核 Cloudflare 补丁明显更少。注意 key 必须传到**下载内核那一步**才有效——工作流已同时传给 install 与运行步骤，并按 `free`/`licensed` 分开缓存，日志会打印 `实际内核: version=... tier=...` 供你确认生效
2. **换住宅/家宽（ISP/原生）出口节点**：Cloudflare 打分主要看 IP 信誉，纯机房 IP 的订阅（哪怕换了国家）通过率都很低

保底方案：本地/Docker 运行（家宽 IP 信誉好得多，实测不触发挑战），用 Windows 任务计划程序定时即可。

**在 Actions 里用你的 Clash 订阅（推荐）**：GitHub 的 runner 无法访问你电脑上的 Clash（`127.0.0.1` 是 runner 自己），所以 workflow 会调用 [clash_proxy.py](clash_proxy.py)（订阅解析 → mihomo 配置生成/启动 → 节点自检，全在一个 Python 脚本里，**本机可直接调试**：`python clash_proxy.py --help`），每次运行时：

1. 订阅来源二选一：`CLASH_SUB_CONTENT`（内容直接注入，**推荐**——很多机场用 Cloudflare 拦 CI 的数据中心 IP，拉链接会 403）或 `CLASH_SUB`（链接，预检 403 会明确报错）
2. 下载 mihomo 内核（固定版本）起本地代理 `127.0.0.1:7897`，用控制 API 确认就绪
3. 过滤掉「剩余流量/到期」等占位节点后，逐个真实节点试访问 linux.do（200 直达或 403+CF 挑战页都算通，被 429 自动换下一个，最多试 10 个）
4. 自检通过后浏览器走该节点出去（相当于把你电脑的 Clash 搬进 CI）；全部不通则降级直连并在日志告警

订阅链接/内容等同密码（内含服务器凭据），只放 Secrets；工作流不会把它打印到日志。

### 代理怎么配（重要）

**程序不强制使用代理，默认就是直连。** 代理只是可选项，填不填取决于你的网络环境：

| 你的环境 | 代理设置 |
|----------|----------|
| 能直接访问 linux.do（国内网络一般可以） | **留空**（直连） |
| TUN 模式 / 虚拟网卡 / 增强模式（Clash Verge、Mihomo、sing-box 等） | **留空**——流量已经在系统网卡层被代理了，浏览器再填 `127.0.0.1:7897` 反而多余，端口没监听时就会报 `ERR_PROXY_CONNECTION_FAILED` |
| 代理软件开了 mixed 端口（如 Clash 的 7897） | 填 `127.0.0.1:7897`（不带 http:// 也可以，程序会自动补全） |
| SOCKS5 代理 | 填 `socks5://127.0.0.1:1080` 或带账号 `socks5://user:pass@host:port` |
| 代理需要用户名密码 | 填 `http://user:pass@host:port` |

GUI：代理输入框留空 = 直连。CLI：不加 `--proxy` = 直连。Docker：不设 `LINUXDO_PROXY` = 直连。

**排查代理问题**：程序内置诊断工具，会启动浏览器实测当前配置能否打开首页，并给出针对性建议：

```bash
python proxy_check.py                # 按当前配置测试（默认直连）
python proxy_check.py 127.0.0.1:7897 # 测试指定代理端口
```

`ERR_PROXY_CONNECTION_FAILED` 的含义：浏览器连不上你配置的代理服务器——代理软件没开、端口不对、或你用了 TUN 模式却还填着代理端口。

## 功能特性

### 核心功能

| 功能             | 描述                                                           |
| ---------------- | -------------------------------------------------------------- |
| **深度爬楼模式** | 完整阅读帖子所有楼层，楼层计数器精确统计爬过的楼层数           |
| **快速浏览模式** | 只爬 3-5 层就换帖，快速增加「浏览话题」数量                    |
| **正确浏览计数** | 点击话题链接进入（而非直接访问 URL），确保「浏览话题」计数增加 |
| **未读话题优先** | 自动识别小蓝点（`new-topic`），优先浏览未读话题                |
| **小蓝点验证**   | 返回板块列表后验证小蓝点消失，确认话题已读                     |
| **按回复数排序** | 进入板块后点击「回复」排序按钮，优先爬高楼多的帖子             |
| **自动点赞**     | 点赞主帖和回复，可自定义概率，默认关闭                         |
| **自动回帖**     | 内置 65 条回复模板，默认关闭（开启时有风险提醒）               |
| **等级追踪**     | 实时获取信任等级、升级要求（connect.linux.do）                 |
| **进度统计**     | 浏览、爬楼、已读总数、点赞、回复，结束时显示真实进度变化       |

### 运行模式

| 模式         | 深度爬楼时的含义               | 快速浏览时的含义      |
| ------------ | ------------------------------ | --------------------- |
| **无尽模式** | 持续运行直到手动停止           | 持续运行直到手动停止  |
| **帖子数量** | 主题数 + 爬楼数 达到目标后停止 | 主题数 达到目标后停止 |
| **时间限制** | 达到指定时间后停止             | 达到指定时间后停止    |

### 防风控机制

- **随机延迟**：所有操作之间随机等待，模拟真人
- **随机滚动**：600-1200px 随机距离，2-4 秒阅读间隔
- **随机行为**：随机板块顺序、随机选帖、随机回复内容
- **CloakBrowser 隐身**：87 项 C++ 源码级指纹补丁，`navigator.webdriver=false`
- **拟人行为**：`humanize=True` 贝塞尔鼠标轨迹、逐字符键盘输入、拟人滚动
- **持久化 profile**：真实用户数据目录，积累缓存/字体/Service Worker，规避无痕检测

### 性能优化（弱网适配）

- **禁用图片加载**（默认开启）：拦截 `image` 类型请求，实测单个板块页可省去 **350 个图片请求**（头像、配图、emoji），显著降低流量；帖子文本、链接、楼层计数、登录表单均不受影响。GUI 有「禁用图片」复选框；CLI/Docker 用 `--load-images` 可改回加载。
- **`domcontentloaded` 导航**：不再等待 `load` 事件（图片等子资源），DOM 解析完成即返回，改由精确的元素等待保证数据就绪——弱网下避免白等 30 秒。
- **渲染等待**：帖子列表、帖子详情、connect 等级页均等待真实渲染完成后再取数（最多 20 秒，超时自动刷新重试一次）。

## 项目结构

```
linuxdo-keep-live/
├── main.py                     # 入口：GUI（默认）/ cli / docker 三个子命令
├── .github/workflows/
│   └── run-schedule.yml        # GitHub Actions 定时无头运行（CloakBrowser + uv）
├── proxy_check.py              # 代理连通性诊断工具
├── login_check.py              # 登录状态诊断工具
├── weaknet_test.py             # 弱网复现测试（限速验证列表等待逻辑）
├── images_test.py              # 图片禁用效果测试（限速对比）
├── smoke_test.py               # 集成冒烟测试（不登录，验证浏览器集成）
├── module_test.py              # 调度器/参数解析单元自测（不启动浏览器）
├── pyproject.toml              # 依赖（cloakbrowser + 可选 gui extras）
├── linuxdo_keep_live/
│   ├── __init__.py             # 版本号
│   ├── config.py               # 板块配置、回复模板、默认参数
│   ├── bot.py                  # 核心 Bot（CloakBrowser 实现，各入口共用）
│   ├── cli.py                  # 无头命令行版
│   ├── docker.py               # Docker 常驻版（随机调度器）
│   └── gui.py                  # tkinter GUI 版（含系统托盘）
└── browser_data/               # 浏览器用户数据目录（运行后生成，保持登录态）
```

### DrissionPage → Playwright API 对照（移植说明）

| linuxdosss（DrissionPage）                        | 本项目（CloakBrowser / Playwright）                                |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| `ChromiumPage(co)`                                | `launch_persistent_context(user_data_dir, ...)` → `ctx.new_page()` |
| `page.get(url)`                                   | `page.goto(url)`                                                   |
| `page.run_js("return f()")`                       | `page.evaluate("() => {...}")`（Playwright 要求函数形式）          |
| `page.ele(sel).click()`                           | `page.locator(sel).click()`                                        |
| `page.ele(sel).input(text)`                       | `page.locator(sel).fill(text)`                                     |
| `page.back()`                                     | `page.go_back()`                                                   |
| `co.set_proxy(p)`                                 | `launch(..., proxy=p)`                                             |
| `co.set_user_data_path(d)`                        | `launch_persistent_context(d, ...)`                                |
| `co.set_argument("--disable-blink-features=...")` | 内置源码级补丁，无需 flag                                          |

## 注意事项

1. **自动回复风险**：据社区反馈，L 站可能存在检测自动回复的机制，曾有用户因自动回复被举报。建议仅使用自动浏览和点赞，谨慎开启自动回复（GUI 开启时有弹窗提醒）。
2. **合理使用**：请合理设置参数，避免过于频繁的操作；建议每天 1-2 次，每次 30-50 帖。
3. **代理**：访问受阻时建议配置代理（住宅 IP 效果更佳），可配合 `geoip=True` 自动匹配时区/语言（源码中已预留参数）。
4. **遵守规则**：请遵守 Linux.do 论坛的社区规则，使用本工具产生的一切后果由使用者自行承担。
5. **登录安全**：程序不保存账号密码，登录在浏览器中完成；凭据仅存于持久化 profile 的 Cookie 中。

## 常见问题（FAQ）

### Q1：我已经登录了，为什么还提示「未检测到登录」？

程序使用**自己独立的浏览器 profile**（`browser_data/`），与您日常用的 Chrome/Edge **完全隔离**——在常用浏览器里登录不算数，必须在**程序弹出的那个浏览器窗口**里登录一次，之后 Cookie 会持久保存。

其他可能原因与对策：

| 原因 | 现象 | 对策 |
|------|------|------|
| 没在本程序窗口登录 | 窗口显示未登录 | 在程序弹出的窗口里登录 |
| Cloudflare 人机验证 | 页面卡在验证，日志有 `Cloudflare挑战=True` | 在窗口里完成验证，程序会自动继续检测 |
| GitHub/Google OAuth 弹窗登录后主窗口头部不刷新 | 明明已登录但检测不到 | 程序每 3 次检测会自动刷新页面重试 |
| 登录态过期/被登出 | 隔几天突然检测不到 | 重新在程序窗口登录一次 |
| 网络/代理问题 | 首页打不开 | 运行 `python proxy_check.py` 排查 |

一键诊断（会告诉您 profile 到底登没登录、通过哪种方式检测、页面现场）：

```bash
python login_check.py
```

### Q2：浏览器启动失败，提示 profile 被占用？

上次浏览器未正常关闭会留下 `SingletonLock` 等锁文件（Chromium exitCode=21）。程序会自动清理重试；若仍失败，手动删除 `browser_data/` 下的 `SingletonLock`、`SingletonSocket`、`SingletonCookie` 后重试，并确认没有其他本程序实例在运行。

### Q3：代理一定要填吗？

不一定，默认直连。TUN 模式（虚拟网卡）请留空，详见上文[代理怎么配](#代理怎么配重要)。

### Q4：网络不好的时候，帖子列表显示 0 个 / 一直跳过板块？

Discourse 是单页应用（SPA），`goto` 返回时列表往往还没渲染，弱网下更慢——盲目等待会取到 0 条。程序已改为**等待列表真实渲染**（最多 20 秒，超时自动刷新重试一次），帖子详情页与 connect 等级页同样改为等待渲染完成后再取数。实测弱网模拟（200KB/s + 400ms 延迟）下可正常取到话题。

## 参考

- [CloakBrowser 官网](https://cloakbrowser.dev/) · [GitHub](https://github.com/CloakHQ/CloakBrowser) · [PyPI](https://pypi.org/project/cloakbrowser/)
- 原项目：[linuxdosss](https://github.com/icysaintdx/linuxdosss)（DrissionPage 版）

## 免责声明

本工具仅供学习交流使用，请勿用于任何违反论坛规则的行为。使用本工具所产生的一切后果由使用者自行承担，与开发者无关。
