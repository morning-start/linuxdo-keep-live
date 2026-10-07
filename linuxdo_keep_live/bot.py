# -*- coding: utf-8 -*-
"""核心机器人：基于 CloakBrowser 的 linux.do 自动浏览。

与参考项目（linuxdosss，基于 DrissionPage）的差异：
    - DrissionPage.ChromiumPage  ->  cloakbrowser.launch_persistent_context
      （CloakBrowser 是 Playwright 的 drop-in 替代，返回标准 Playwright 对象）
    - page.get(url)              ->  page.goto(url)
    - page.run_js(...)           ->  page.evaluate(...)
    - page.ele(sel).click()      ->  page.locator(sel).click()（humanize 后行为拟人）
    - page.ele(sel).input(text)  ->  page.locator(sel).fill(text)
    - page.back()                ->  page.go_back()
    - co.set_proxy(...)          ->  launch(..., proxy=...)
    - co.set_user_data_path(...) ->  launch_persistent_context(user_data_dir, ...)
    - --disable-blink-features=AutomationControlled
                                ->  CloakBrowser 内置 87 项 C++ 源码级指纹补丁
    - 新增 humanize=True：贝塞尔鼠标轨迹、逐字符键盘输入、拟人滚动
"""

import json
import os
import random
import time
import urllib.request
from datetime import datetime

from cloakbrowser import launch_persistent_context

# ==================== JS 片段（自参考项目移植） ====================

# 注意：Playwright 的 page.evaluate 需要「函数」而非裸语句，
# 因此所有片段统一包成箭头函数（DrissionPage 的 run_js 可直接写 return）。

# 获取信任等级与升级要求（connect.linux.do 新版页面结构）
JS_GET_LEVEL_INFO = """
() => {
function getLevelInfo() {
    const result = {
        username: '',
        level: '',
        nextLevel: '',
        requirements: []
    };

    // 获取用户名（从 card-subtitle 中提取）
    const subtitle = document.querySelector('.card-subtitle');
    if (subtitle) {
        const text = subtitle.textContent;
        const match = text.match(/@([^\\s·]+)/);
        if (match) {
            result.username = match[1];
        }
    }

    // 获取下一级要求（从 card-title 中提取）
    const cardTitle = document.querySelector('.card-title');
    if (cardTitle) {
        const text = cardTitle.textContent;
        const match = text.match(/信任级别\\s*(\\d+)/);
        if (match) {
            result.nextLevel = match[1];
            // 当前等级 = 目标等级 - 1
            result.level = String(parseInt(match[1]) - 1);
        }
    }

    // 获取活跃程度数据（tl3-ring 结构）
    const rings = document.querySelectorAll('.tl3-ring');
    rings.forEach(ring => {
        const label = ring.querySelector('.tl3-ring-label');
        const current = ring.querySelector('.tl3-ring-current');
        const target = ring.querySelector('.tl3-ring-target');

        if (label && current && target) {
            const name = label.textContent.trim();
            const currentVal = current.textContent.trim();
            const targetVal = target.textContent.replace('/', '').trim();

            result.requirements.push({
                name: name,
                current: currentVal,
                required: targetVal
            });
        }
    });

    // 获取互动参与数据（tl3-bar 结构）
    const bars = document.querySelectorAll('.tl3-bar-item');
    bars.forEach(bar => {
        const label = bar.querySelector('.tl3-bar-label');
        const nums = bar.querySelector('.tl3-bar-nums');

        if (label && nums) {
            const name = label.textContent.trim();
            const numsText = nums.textContent.trim();
            const match = numsText.match(/(\\d+)\\/(\\d+)/);

            if (match) {
                result.requirements.push({
                    name: name,
                    current: match[1],
                    required: match[2]
                });
            }
        }
    });

    // 获取合规记录数据（tl3-quota 结构）
    const quotas = document.querySelectorAll('.tl3-quota-card');
    quotas.forEach(quota => {
        const label = quota.querySelector('.tl3-quota-label');
        const nums = quota.querySelector('.tl3-quota-nums');

        if (label && nums) {
            const name = label.textContent.trim();
            const numsText = nums.textContent.trim();
            const match = numsText.match(/(\\d+)\\s*\\/\\s*(\\d+)/);

            if (match) {
                result.requirements.push({
                    name: name,
                    current: match[1],
                    required: match[2]
                });
            }
        }
    });

    // 获取禁言/封禁数据（tl3-veto 结构）
    const vetos = document.querySelectorAll('.tl3-veto-item');
    vetos.forEach(veto => {
        const label = veto.querySelector('.tl3-veto-label');
        const value = veto.querySelector('.tl3-veto-value');

        if (label && value) {
            const name = label.textContent.trim();
            const currentVal = value.textContent.trim();

            result.requirements.push({
                name: name,
                current: currentVal,
                required: '0'
            });
        }
    });

    return result;
}
return getLevelInfo();
}
"""

# 获取板块帖子列表（区分未读/已读，未读话题带小蓝点）
JS_GET_TOPICS = """
() => {
function getTopics() {
    const rows = document.querySelectorAll('tr.topic-list-item');
    const unreadTopics = [];  // 未读话题（带小蓝点）
    const readTopics = [];    // 已读话题（无小蓝点）

    rows.forEach(row => {
        const link = row.querySelector('a.title.raw-link.raw-topic-link');
        if (link) {
            const href = link.getAttribute('href');
            const title = link.textContent.trim();
            const topicId = row.getAttribute('data-topic-id');

            // 跳过置顶帖
            if (href && title && !row.classList.contains('pinned')) {
                // 检查是否有小蓝点（未读标记）
                const newTopicBadge = row.querySelector('.badge.badge-notification.new-topic');

                const topicData = {
                    url: href,
                    title: title.substring(0, 50),
                    id: topicId,
                    isUnread: !!newTopicBadge  // 是否未读
                };

                if (newTopicBadge) {
                    unreadTopics.push(topicData);
                } else {
                    readTopics.push(topicData);
                }
            }
        }
    });

    // 优先返回未读话题，如果没有未读的再返回已读的
    return {
        unread: unreadTopics,
        read: readTopics,
        all: [...unreadTopics, ...readTopics]
    };
}
return getTopics();
}
"""

# 获取楼层信息（当前楼层/总楼层）
# 支持两种显示格式：
#   1. 宽窗口：.timeline-replies 显示 "1/169"
#   2. 窄窗口：#topic-progress .nums 显示 <span>69</span><span>/</span><span>74</span>
JS_GET_FLOOR_INFO = """
() => {
function getFloorInfo() {
    // 方法1：尝试从 .timeline-replies 获取（宽窗口）
    const timelineElement = document.querySelector('.timeline-replies');
    if (timelineElement) {
        const text = timelineElement.textContent.trim();
        const match = text.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
        if (match) {
            return {
                current: parseInt(match[1]),
                total: parseInt(match[2]),
                source: 'timeline-replies'
            };
        }
    }

    // 方法2：尝试从 #topic-progress .nums 获取（窄窗口）
    const progressElement = document.querySelector('#topic-progress .nums');
    if (progressElement) {
        const spans = progressElement.querySelectorAll('span');
        if (spans.length >= 3) {
            const current = parseInt(spans[0].textContent);
            const total = parseInt(spans[2].textContent);
            if (!isNaN(current) && !isNaN(total)) {
                return {
                    current: current,
                    total: total,
                    source: 'topic-progress'
                };
            }
        }
    }

    return null;
}
return getFloorInfo();
}
"""

# 统计点赞按钮数量
JS_COUNT_LIKE_BUTTONS = (
    "() => document.querySelectorAll('button.btn-toggle-reaction-like').length"
)

# 判断是否滚动到页面底部
JS_AT_BOTTOM = (
    "() => (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 100"
)

# Discourse 官方会话 API：已登录返回 200 + current_user，未登录返回 403。
# 比 DOM 选择器更可靠（不受主题改版/头部未渲染影响）。
JS_CHECK_SESSION = """
async () => {
    try {
        const r = await fetch('/session/current.json', {
            credentials: 'include',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        });
        if (r.status === 200) {
            const j = await r.json();
            const u = (j.current_user && j.current_user.username) || j.username || null;
            return {loggedIn: true, username: u};
        }
        return {loggedIn: false, status: r.status};
    } catch (e) {
        return {loggedIn: null, error: String(e)};
    }
}
"""

# 登录检测用的 DOM 标记（#current-user 是 Discourse 标准用户菜单）
LOGIN_SELECTORS = [
    "#current-user",
    ".current-user",
    "a.header-dropdown-toggle.current-user",
]

# profile 被占用时的提示（Chromium exitCode=21）
PROFILE_LOCK_HINT = (
    "浏览器 profile 被占用：请确认没有其他本程序实例在运行，"
    "或浏览器上次未正常关闭。可尝试删除 browser_data 下的 SingletonLock / SingletonSocket / SingletonCookie 文件后重试"
)

# 默认浏览器视口（宽窗口才会显示 .timeline-replies 楼层计时器）
DEFAULT_VIEWPORT = {"width": 1200, "height": 1080}

# 用户数据目录（持久化 profile，保持登录状态）
DEFAULT_USER_DATA_DIR = os.path.join(os.getcwd(), "browser_data")


def normalize_proxy(proxy):
    """归一化代理地址：'127.0.0.1:7897' -> 'http://127.0.0.1:7897'。

    CloakBrowser 的 proxy 参数接受 http:// / socks5:// 开头的地址，
    也接受 {"server": ..., "username": ..., "password": ..., "bypass": ...} 字典。
    """
    if not proxy:
        return None
    proxy = str(proxy).strip()
    if not proxy:
        return None
    if "," in proxy:
        # 多个候选代理（逗号分隔，如 mihomo 输出的 http://127.0.0.1:7897,http://127.0.0.1:7890）
        # 取第一个即可——mihomo 的 mixed-port 同时收 HTTP/SOCKS，一个就够
        proxy = proxy.split(",")[0].strip()
    if "://" in proxy:
        return proxy
    return "http://" + proxy


def is_proxy_error(error):
    """判断是否为代理连接失败（Chromium net error）。

    常见于：代理软件未启动、端口不对、代理需要认证、代理已关闭。
    """
    msg = str(error).upper()
    return (
        "ERR_PROXY_CONNECTION_FAILED" in msg
        or "ERR_NO_SUPPORTED_PROXIES" in msg
        or "ERR_TUNNEL_CONNECTION_FAILED" in msg
        or ("ERR_PROXY" in msg)
    )


# 运行目标解析：把 "30" / "30min" / "1h" 这类目标字符串解析为 (mode, target_value)。
# 带时间单位 = 按时间运行；纯数字 = 按帖子数量运行；识别不了走默认（30 分钟）。
TARGET_DEFAULT = ("time", 30)  # 识别不了时的默认目标：30 分钟


def parse_target(value, default=None):
    """解析运行目标字符串，返回 (mode, target_value)。

    规则：
        - "30"      -> ("topics", 30)   按 30 个帖子
        - "30min"   -> ("time", 30)     按 30 分钟
        - "1h"      -> ("time", 60)     按 1 小时
        - "90s"     -> ("time", 1.5)    按 90 秒
        - "" / None / 识别不了 -> default（默认 30 分钟）

    支持的单位：min/m/分钟（分钟），h/小时（小时），s/秒（秒）。
    数量支持纯数字或带 "帖"/"个"/"topics" 后缀。
    """
    if default is None:
        default = TARGET_DEFAULT

    if value is None:
        return default
    s = str(value).strip().lower()
    if not s:
        return default

    # 提取数字部分（整数或小数）与单位部分
    import re

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", s)
    if not m:
        return default
    num = float(m.group(1))
    unit = m.group(2).strip()

    if unit in ("", "帖", "个", "topic", "topics"):
        if num <= 0 or num != int(num):
            return default
        return ("topics", int(num))

    if unit in ("min", "mins", "m", "分钟"):
        if num <= 0:
            return default
        return ("time", num)

    if unit in ("h", "hr", "hour", "hours", "小时"):
        if num <= 0:
            return default
        return ("time", num * 60)

    if unit in ("s", "sec", "secs", "秒"):
        if num <= 0:
            return default
        return ("time", num / 60)

    return default


# 代理失败时给出的可操作提示
PROXY_FAIL_HINT = (
    "代理连接失败：请检查代理软件是否正在运行、端口是否正确；"
    "不需要代理时请清空代理设置（GUI 代理输入框留空 / 不加 --proxy / 不设置 LINUXDO_PROXY）"
)


def detect_screen_height(default=1080):
    """尽力探测屏幕高度（GUI 环境下用于设置视口高度）。"""
    try:
        import tkinter as tk

        root = tk.Tk()
        height = root.winfo_screenheight()
        root.destroy()
        return max(720, int(height))
    except Exception:
        return default


class Bot:
    """Linux.do 自动浏览机器人（CloakBrowser 版）"""

    def __init__(
        self,
        cfg,
        cats,
        lg,
        update_info=None,
        update_progress=None,
        update_countdown=None,
        mode="endless",
        target_value=0,
        enable_like=True,
        enable_reply=True,
        enable_wait=True,
        browse_mode="deep",
        headless=False,
        humanize=True,
        block_images=True,
        viewport=None,
        user_data_dir=None,
    ):
        self.cfg = cfg
        self.cats = cats
        self.lg = lg
        self.update_info = update_info
        self.update_progress = update_progress  # 更新进度回调
        self.update_countdown = update_countdown  # 更新倒计时回调
        self.mode = mode  # 运行模式：endless(无尽), topics(帖子数), time(时间限制)
        self.target_value = target_value  # 目标值：帖子数或分钟数
        self.enable_like = enable_like  # 是否启用自动点赞
        self.enable_reply = enable_reply  # 是否启用自动回复
        self.enable_wait = enable_wait  # 是否启用等待时间
        self.browse_mode = browse_mode  # 浏览模式：deep(深度爬楼), quick(快速浏览3-5层)
        self.headless = headless  # 是否无头模式
        self.humanize = humanize  # CloakBrowser 拟人行为
        self.block_images = block_images  # 禁用图片加载（提速）
        self.viewport = viewport or dict(DEFAULT_VIEWPORT)
        self.user_data_dir = user_data_dir or DEFAULT_USER_DATA_DIR
        self.ctx = None  # CloakBrowser 持久化上下文
        self.pg = None  # Playwright Page
        self.run = False
        self.stats = {"topic": 0, "like": 0, "reply": 0, "like_reply": 0, "floors": 0}
        self.user_info = None
        self.level_requirements = []  # 保存升级要求
        self.initial_level_info = None  # 保存初始等级信息用于对比
        self.start_time = None  # 记录开始时间
        # Clash 节点轮换（CI 过 Cloudflare 用）：登录卡挑战时经 mihomo API 换出口 IP 再试
        self.clash_api = (os.environ.get("CLASH_ROTATE_API") or "").rstrip("/")
        self._clash_nodes = None
        self._clash_i = 1  # all[0] 已被 clash_proxy 选中，轮换从下一个开始

    # ---------------- 防风控 ----------------

    def _random_delay(self, min_sec=0.5, max_sec=2.0, reason=""):
        """防风控：随机延迟

        分段睡眠并检查 self.run：点停止后最长 0.5 秒内响应，
        而不是睡完整个随机延迟（可能长达十几秒）。
        """
        delay = random.uniform(min_sec, max_sec)
        if reason:
            self.lg(f"[防风控] {reason}，等待 {delay:.1f}s")
        self._wait_seconds(delay)

    def _wait_seconds(self, seconds):
        """分段睡眠，期间任务被停止/达标时立即返回"""
        end = time.time() + seconds
        while self.run:
            remain = end - time.time()
            if remain <= 0:
                break
            time.sleep(min(0.5, remain))

    # ---------------- 浏览器管理 ----------------

    @staticmethod
    def _clear_profile_locks(user_data_dir):
        """清理 Chromium 残留的 Singleton 锁文件（上次未正常关闭时会出现）"""
        removed = []
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            path = os.path.join(user_data_dir, name)
            try:
                if os.path.exists(path):
                    os.remove(path)
                    removed.append(name)
            except Exception:
                pass
        return removed

    def start(self):
        """启动 CloakBrowser（持久化 profile，保持登录状态）"""
        # 确保先关闭旧的浏览器实例
        if self.ctx:
            self.lg("关闭旧的浏览器实例...")
            self.close()
            time.sleep(1)  # 等待浏览器完全关闭

        self.lg("启动浏览器 (CloakBrowser)...")

        # 重试机制（处理偶发启动失败，如首次下载/端口占用/profile 锁残留）
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 视口高度尽量贴合屏幕（宽窗口才会显示楼层计时器）
                if not self.headless:
                    self.viewport = dict(self.viewport)
                    self.viewport.setdefault(
                        "height", detect_screen_height(self.viewport.get("height", 1080))
                    )

                kwargs = {
                    "headless": self.headless,
                    "humanize": self.humanize,
                    "viewport": self.viewport,
                }
                proxy = normalize_proxy(self.cfg.get("proxy"))
                if proxy:
                    kwargs["proxy"] = proxy
                    self.lg(f"已设置代理: {proxy}")

                os.makedirs(self.user_data_dir, exist_ok=True)
                self.lg(f"用户数据目录: {self.user_data_dir}")

                # CloakBrowser：返回标准 Playwright BrowserContext
                self.ctx = launch_persistent_context(self.user_data_dir, **kwargs)

                # 禁用图片加载：弱网下显著降低流量与首屏时间（帖子文本/计数不受影响）
                if self.block_images:
                    self.ctx.route("**/*", self._on_route)
                    self.lg("已禁用图片加载（提速）")

                self.pg = self.ctx.new_page()
                self.lg("浏览器就绪")
                return True

            except Exception as e:
                msg = str(e)
                # profile 被占用（Chromium exitCode=21）：清理残留锁文件后重试
                if "has been closed" in msg or "Process" in msg and "exited" in msg:
                    removed = self._clear_profile_locks(self.user_data_dir)
                    if removed:
                        self.lg(f"清理残留 profile 锁文件: {', '.join(removed)}")
                if attempt < max_retries - 1:
                    self.lg(f"启动失败（尝试 {attempt + 1}/{max_retries}），重试中: {msg[:200]}")
                    time.sleep(2)
                    continue
                self.lg(f"启动失败: {msg[:300]}")
                if "has been closed" in msg:
                    self.lg("⚠ " + PROFILE_LOCK_HINT)
                return False

        return False

    def stop(self):
        self.run = False

    # ---------------- 请求拦截 ----------------

    def _on_route(self, route):
        """请求路由：拦截图片请求以节省流量、降低首屏时间。

        只拦 resource_type == 'image'（头像、帖子配图、emoji 图等），
        不影响 HTML/CSS/JS/XHR——帖子列表、楼层计数、登录表单均正常。
        对页面表现为「图片加载失败」，与用户主动禁用图片无异。
        """
        try:
            if route.request.resource_type == "image":
                route.abort()
            else:
                route.continue_()
        except Exception:
            # 极端情况下拦截器本身出错时放行，避免拖慢页面
            try:
                route.continue_()
            except Exception:
                pass

    def close(self):
        if self.ctx:
            try:
                self.ctx.close()
            except Exception as e:
                self.lg(f"关闭浏览器时出错: {e}")
            self.ctx = None  # 清空引用
            self.pg = None

    # ---------------- 页面工具 ----------------

    def _goto_with_hint(self, url, what="页面"):
        """导航到 url；失败时记录原因，代理失败额外给出可操作提示

        使用 wait_until='domcontentloaded'：不等图片等子资源（load 事件），
        DOM 解析完成即返回，后续由各步骤的元素等待保证数据就绪。
        """
        try:
            self.pg.goto(url, wait_until="domcontentloaded")
            return True
        except Exception as e:
            self.lg(f"打开{what}失败: {e}")
            if is_proxy_error(e):
                self.lg("⚠ " + PROXY_FAIL_HINT)
            return False

    def _has(self, selector, timeout_ms=3000):
        """判断元素是否存在（不依赖交互，仅 attached 即可）"""
        try:
            self.pg.wait_for_selector(selector, timeout=timeout_ms, state="attached")
            return True
        except Exception:
            return False

    # ---------------- 登录检测 ----------------

    def _api_check_login(self):
        """通过 Discourse 会话 API 检测登录状态（比 DOM 更可靠）

        Returns:
            (logged_in, username)：logged_in 为 True/False/None（None 表示无法判断）
        """
        try:
            result = self.pg.evaluate(JS_CHECK_SESSION)
            if not result:
                return None, None
            if result.get("loggedIn") is True:
                return True, result.get("username")
            if result.get("loggedIn") is False:
                return False, None
            return None, None
        except Exception:
            return None, None

    def _detect_login(self, dom_timeout_ms=3000):
        """综合检测登录状态：先查 DOM 标记，查不到再走会话 API

        Returns:
            dict: {found, via, username, diag}
        """
        # 1) DOM 标记（快速，覆盖绝大多数情况）
        for sel in LOGIN_SELECTORS:
            if self._has(sel, timeout_ms=dom_timeout_ms):
                return {"found": True, "via": "dom", "username": None, "diag": {}}

        # 2) 会话 API（主题改版 / 头部未渲染时兜底）
        logged_in, username = self._api_check_login()
        if logged_in:
            return {"found": True, "via": "api", "username": username, "diag": {}}

        # 3) 未检测到：采集页面现场，便于定位原因
        diag = self._page_diag()
        return {
            "found": False,
            "via": None,
            "username": None,
            "diag": diag,
        }

    def _page_diag(self):
        """采集当前页面状态（登录检测失败时用于日志诊断）"""
        try:
            return self.pg.evaluate(
                """() => ({
                    title: document.title,
                    hasCurrentUser: !!document.querySelector('#current-user'),
                    hasLoginLink: Array.from(document.querySelectorAll('a')).some(a => (a.getAttribute('href')||'').includes('/login')),
                    cf: !!document.querySelector('#challenge-form, #cf-chl-widget, .cf-browser-verification, script[src*="challenges.cloudflare.com"]'),
                    bodyStart: document.body ? document.body.innerText.slice(0, 80) : ''
                })"""
            )
        except Exception:
            return {}

    # ---------------- 页面加载等待（弱网适配） ----------------

    def _wait_topic_list(self, timeout_ms=20000):
        """等待板块帖子列表渲染完成

        Discourse 是 SPA：goto 返回时列表往往还没渲染，弱网下更慢。
        盲目 sleep 会取到 0 个帖子，这里改为等待行元素真实出现。
        """
        try:
            self.pg.wait_for_selector(
                "tr.topic-list-item", timeout=timeout_ms, state="attached"
            )
            return True
        except Exception:
            return False

    def _wait_topic_page(self, timeout_ms=20000):
        """等待帖子详情页内容渲染（楼层计时器 / 帖子流出现）"""
        selectors = [
            "#post-stream .topic-post",
            ".post-stream article",
            "#topic-progress",
            ".timeline-replies",
        ]
        last_err = None
        for sel in selectors:
            try:
                self.pg.wait_for_selector(sel, timeout=timeout_ms, state="attached")
                return True
            except Exception as e:
                last_err = e
        # 全部超时也算到达（至少有页面），由调用方按降级逻辑处理
        return False

    def _wait_level_page(self, timeout_ms=15000):
        """等待 connect 等级页面渲染（卡片/进度环出现）"""
        for sel in [".card-title", ".tl3-ring", ".tl3-bar-item", ".tl3-quota-card"]:
            try:
                self.pg.wait_for_selector(sel, timeout=timeout_ms, state="attached")
                return True
            except Exception:
                continue
        return False

    # ---------------- 登录 ----------------

    def check_login(self, wait_for_login=True, max_wait=600, check_interval=15):
        """检查登录状态（等待用户在浏览器中手动登录）

        检测策略（按优先级）：
            1. DOM 标记 #current-user / .current-user（Discourse 标准用户菜单）
            2. /session/current.json 会话 API（主题改版或头部未渲染时兜底）
        每 3 次未检测到会刷新一次页面，避免 OAuth 弹窗登录后主窗口头部不更新的情况。
        """
        self.lg("检查登录...")
        if not self._goto_with_hint(self.cfg["base"], "首页"):
            return False
        time.sleep(3)

        start_time = time.time()
        check_count = 0
        first_check = True

        while self.run:
            check_count += 1
            try:
                result = self._detect_login()
                if result["found"]:
                    username = result.get("username") or (
                        self.user_info.get("username") if self.user_info else None
                    )
                    try:
                        img = self.pg.locator("#current-user img")
                        username = (
                            img.first.get_attribute("title")
                            if img.count() > 0
                            else (username or "用户")
                        )
                    except Exception:
                        pass
                    self.user_info = {"username": username or "用户"}
                    self.lg(
                        f"已登录: {self.user_info['username']}"
                        + (f"（通过 {result['via']} 检测）" if result.get("via") else "")
                    )
                    return True
            except Exception as e:
                self.lg(f"登录检测异常: {e}")

            # 未登录
            if not wait_for_login:
                self.lg("未登录，请先登录")
                return False

            # 检查是否超时
            elapsed = time.time() - start_time
            remaining = max_wait - elapsed

            if remaining <= 0:
                self.lg("等待登录超时，请重新启动")
                return False

            if first_check:
                self.lg("未检测到登录，请在浏览器中完成登录")
                self.lg("提示：登录成功后会自动检测，无需其他操作")
                self.lg(f"检查间隔：{check_interval}秒，最长等待：{int(remaining)}秒")
                first_check = False
            else:
                # 每 3 次未检测到：输出一次页面现场 + 刷新页面（修复头部不更新）
                if check_count % 3 == 0:
                    self._log_login_diag()
                    self.lg("刷新页面重新检测登录状态...")
                    try:
                        self.pg.evaluate("location.reload()")
                        time.sleep(3)
                    except Exception:
                        pass
                else:
                    self.lg(f"第{check_count}次检查，未检测到登录，剩余等待{int(remaining)}秒")

            # 等待一段时间后重新检查（不刷新页面，避免打断用户输入）
            time.sleep(check_interval)

        return False

    def _log_login_diag(self):
        """输出页面现场，帮助定位登录检测失败的原因"""
        try:
            diag = self._page_diag()
            if not diag:
                return
            self.lg(
                f"页面状态: 标题={diag.get('title', '?')!r} | "
                f"#current-user={diag.get('hasCurrentUser')} | "
                f"登录链接={diag.get('hasLoginLink')} | "
                f"Cloudflare挑战={diag.get('cf')} | "
                f"正文开头={str(diag.get('bodyStart', ''))[:40]!r}"
            )
            if diag.get("cf"):
                self.lg("⚠ 检测到 Cloudflare 人机验证页面：请在弹出的浏览器中完成验证后再登录")
        except Exception:
            pass

    def _check_login(self):
        """静默检查登录状态（访问首页判断是否已登录）"""
        try:
            if not self._goto_with_hint(self.cfg["base"], "首页"):
                return False
            self._random_delay(2, 3)
            result = self._detect_login()
            return result["found"]
        except Exception:
            return False

    def login(self, username, password):
        """使用账号密码自动登录（无头版 / Docker 用）

        强化点（GitHub Actions 首跑失败复盘）：
            - 登录入口先试首页「登录」按钮（Discourse SPA 弹出登录模态框），
              失败再退回 /login 独立页 —— 有些环境直接开 /login 会被重定向
            - 表单等待用 wait_for_selector 显式等待（默认 20s，弱网/风控页慢），
              而不是 fill() 的默认超时；等待期间输出页面现场便于定位
            - 等不到表单时自动重试整段流程（Cloudflare 挑战通常几秒后放行）
        """
        self.lg("开始登录...")

        # 启用 Clash 轮换时多给几次机会（每次换个出口 IP 过 CF）
        max_attempts = 6 if self.clash_api else 3
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    self.lg(f"登录重试（第 {attempt}/{max_attempts} 次）...")
                    self._wait_seconds(3)
                    # 换一个 Clash 出口节点再试（当前节点 IP 可能被 CF 硬拦）
                    self._rotate_clash_node()

                # ---- 进入登录界面 ----
                if self._open_login_ui():
                    # Cloudflare 挑战页：给 CloakBrowser 时间自动通过。
                    # 关键：挑战解析期间【绝不刷新】——刷新会重置挑战，永远过不了。
                    self._wait_cf_clear(timeout_s=60)

                    # ---- 等待登录表单出现 ----
                    if not self._wait_login_form():
                        reason = self._rate_limited_or_challenge()
                        self._save_login_debug(f"login-no-form-attempt{attempt}")
                        if reason == "rate_limited":
                            # 429 限流：短间隔重试毫无意义，等 60s 让限流窗口过去
                            if attempt < max_attempts:
                                self.lg("检测到限流页（HTTP 429），等待 60s 后重试...")
                                self._wait_seconds(60)
                                continue
                            self.lg("多次重试仍被限流，任务终止")
                            return False
                        if reason == "challenge":
                            self.lg("仍卡在 Cloudflare 挑战页，重试（节点 IP 信誉可能较差）...")
                        else:
                            self.lg("登录表单未出现（可能被风控页拦截），重试...")
                        continue

                    # ---- 填表并提交 ----
                    self.lg("输入用户名...")
                    self.pg.locator("#login-account-name").fill(username)
                    self._random_delay(0.5, 1, "输入用户名后")

                    self.lg("输入密码...")
                    self.pg.locator("#login-account-password").fill(password)
                    self._random_delay(0.5, 1, "输入密码后")

                    self.lg("点击登录按钮...")
                    self.pg.locator("#login-button").click()

                    # 等待登录完成
                    self._random_delay(3, 5, "等待登录")

                    # 验证登录状态
                    if self._check_login():
                        self.lg("登录成功")
                        return True
                    self.lg("登录表单提交后未检测到登录态，请检查用户名和密码")
                    self._log_login_diag()
                    self._save_login_debug("login-submit-failed")
                    # 提交成功但验证失败：多半是密码错误，重试意义不大
                    return False
                else:
                    self.lg("无法进入登录界面，重试...")
                    self._save_login_debug(f"login-no-entry-attempt{attempt}")
            except Exception as e:
                self.lg(f"登录过程出错: {e}")

        return False

    def _rotate_clash_node(self):
        """经 mihomo 控制 API 切换到下一个出口节点。

        登录卡在 Cloudflare 挑战时，换一个 IP 信誉可能更好的节点再试
        （150 个节点里往往有个别能过 CF）。仅当设置 CLASH_ROTATE_API 时生效。

        Returns:
            新节点名，或 None（未启用/失败）。
        """
        if not self.clash_api:
            return None
        try:
            if self._clash_nodes is None:
                raw = json.loads(
                    urllib.request.urlopen(f"{self.clash_api}/proxies/PROXY", timeout=5).read()
                )
                self._clash_nodes = [
                    n for n in (raw.get("all") or []) if n not in ("DIRECT", "REJECT", "PROXY")
                ]
            if not self._clash_nodes:
                return None
            name = self._clash_nodes[self._clash_i % len(self._clash_nodes)]
            self._clash_i += 1
            req = urllib.request.Request(
                f"{self.clash_api}/proxies/PROXY",
                method="PUT",
                data=json.dumps({"name": name}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5).read()
            self.lg(f"切换 Clash 出口节点 -> {name}")
            self._wait_seconds(1)
            return name
        except Exception as e:
            self.lg(f"切换 Clash 节点失败: {e}")
            return None

    def _wait_cf_clear(self, timeout_s=60):
        """Cloudflare 挑战页出现时，等待 CloakBrowser 自动通过。

        关键原则：挑战解析期间【绝不刷新页面】——刷新会重置 CF 的托管挑战进度，
        导致永远过不了。这里只静默轮询标题/特征，给内核足够时间自行完成验证。

        Returns:
            True  挑战已通过（或本就没有挑战）
            False 超时仍卡在挑战页
        """
        deadline = time.time() + timeout_s
        seen = False
        while self.run and time.time() < deadline:
            diag = self._page_diag()
            title = (diag.get("title") or "").lower()
            challenging = (
                bool(diag.get("cf"))
                or "just a moment" in title
                or "checking your browser" in title
            )
            if not challenging:
                if seen:
                    self.lg("Cloudflare 挑战已通过")
                return True
            if not seen:
                self.lg(f"检测到 Cloudflare 挑战页，等待自动通过（不刷新，最长 {timeout_s}s）...")
                seen = True
            time.sleep(2)
        return not self._page_diag().get("cf")

    def _rate_limited_or_challenge(self):
        """判断当前页面是限流页（HTTP 429）还是其他风控拦截

        Returns:
            "rate_limited"  站点限流页（正文就是 "Too Many Requests"）
            "challenge"     Cloudflare 等挑战页
            "other"         其他情况
        """
        try:
            body = (self.pg.evaluate("() => document.body ? document.body.innerText : ''") or "").strip()
        except Exception:
            return "other"
        if "too many requests" in body.lower():
            return "rate_limited"
        diag = self._page_diag()
        if diag.get("cf"):
            return "challenge"
        return "other"

    def _save_login_debug(self, name):
        """登录失败时保存页面截图与 HTML 快照到 browser_data/debug/（尽力而为）

        GitHub Actions 上失败时配合 upload-artifact 下载排查；本地调试也适用。
        文件不含账号密码，但截图可能包含页面内容，勿外传。
        """
        try:
            debug_dir = os.path.join(self.user_data_dir, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            shot = os.path.join(debug_dir, f"{name}-{ts}.png")
            self.pg.screenshot(path=shot, full_page=False)
            self.lg(f"已保存登录失败截图: {shot}")
            html = os.path.join(debug_dir, f"{name}-{ts}.html")
            with open(html, "w", encoding="utf-8") as f:
                f.write(self.pg.content())
            self.lg(f"已保存页面快照: {html}")
        except Exception as e:
            self.lg(f"保存登录调试信息失败: {e}")

    def _open_login_ui(self):
        """进入登录界面：优先首页「登录」按钮（SPA 模态框），退回 /login 独立页"""
        # 方式一：首页点击「登录」按钮（Discourse 标准路径，弹出登录模态框）
        if self._goto_with_hint(self.cfg["base"], "首页"):
            self._random_delay(1, 2, "首页加载")
            try:
                btn = self.pg.locator(".login-button, button.login-button").first
                btn.wait_for(state="visible", timeout=8000)
                btn.click()
                self.lg("已点击首页登录按钮")
                self._random_delay(1, 2, "等待登录框弹出")
                return True
            except Exception:
                self.lg("首页登录按钮不可用，尝试直接打开登录页...")

        # 方式二：直接访问 /login 独立页
        login_url = f"{self.cfg['base']}/login"
        return self._goto_with_hint(login_url, "登录页")

    def _wait_login_form(self, timeout_ms=20000):
        """等待登录表单渲染完成，期间输出页面现场（首次超时一半时输出一次）"""
        reported = False
        try:
            self.pg.wait_for_selector(
                "#login-account-name", timeout=timeout_ms, state="attached"
            )
            self.pg.wait_for_selector(
                "#login-account-password", timeout=5000, state="attached"
            )
            return True
        except Exception:
            pass

        # 用户名框等到了但密码框没有：输出现场，再补等一轮
        if self._has("#login-account-name", timeout_ms=1000):
            self._log_login_diag()
            try:
                self.pg.wait_for_selector(
                    "#login-account-password", timeout=10000, state="attached"
                )
                return True
            except Exception:
                return False

        # 完全没等到：等待过半时输出一次现场，帮助判断是否为 Cloudflare 拦截
        remaining = timeout_ms / 1000 / 2
        while remaining > 0 and not reported:
            self._wait_seconds(min(1.0, remaining))
            remaining -= 1.0
            if self._has("#login-account-name", timeout_ms=500):
                try:
                    self.pg.wait_for_selector(
                        "#login-account-password", timeout=5000, state="attached"
                    )
                    return True
                except Exception:
                    return False
            if remaining <= timeout_ms / 1000 / 4:
                self._log_login_diag()
                reported = True
        return False

    # ---------------- 等级信息 ----------------

    def get_level_info(self, is_final=False):
        """获取等级信息"""
        self.lg("获取等级信息...")
        try:
            # 如果是最终获取，先强制刷新页面确保数据最新
            if is_final:
                self.lg("强制刷新页面获取最新数据...")
                if not self._goto_with_hint(self.cfg["connect"], "connect 页面"):
                    return None
                time.sleep(2)
                # 刷新页面
                self.pg.evaluate("location.reload(true)")
                self._wait_level_page()
                time.sleep(4)
            else:
                if not self._goto_with_hint(self.cfg["connect"], "connect 页面"):
                    return None
                # 等待卡片/进度环渲染（弱网适配）
                self._wait_level_page()
                time.sleep(2)

            info = self.pg.evaluate(JS_GET_LEVEL_INFO)

            if info:
                self.user_info = info
                self.lg("用户: " + info.get("username", "未知"))
                self.lg("当前等级: " + info.get("level", "未知") + "级")
                if info.get("nextLevel"):
                    self.lg("下一级: " + info.get("nextLevel") + "级")
                if info.get("requirements"):
                    self.lg("升级要求:")
                    for req in info["requirements"][:8]:
                        self.lg(
                            "  "
                            + req["name"]
                            + ": "
                            + req["current"]
                            + "/"
                            + req["required"]
                        )

                # 更新GUI显示
                if self.update_info:
                    self.update_info(info, is_final)

                # 保存升级要求用于进度追踪
                self.level_requirements = info.get("requirements", [])

                # 首次获取时保存初始等级信息
                if not is_final and self.initial_level_info is None:
                    self.initial_level_info = info.copy()

                return info
        except Exception as e:
            self.lg("获取等级失败: " + str(e))
        return None

    # ---------------- 帖子列表 ----------------

    def get_topics(self, cat):
        """使用JS获取帖子列表（按回复数排序，优先未读话题）"""
        url = self.cfg["base"] + cat["u"]
        self.lg("进入板块: " + cat["n"])
        if not self._goto_with_hint(url, f"板块 {cat['n']}"):
            return []
        self._random_delay(2, 4, "页面加载")

        # 等待帖子列表真正渲染（弱网下 SPA 渲染慢，避免取到 0 条）
        if not self._wait_topic_list():
            self.lg("帖子列表未加载出来，刷新重试...")
            try:
                self.pg.evaluate("location.reload()")
                self._random_delay(2, 3, "刷新后等待")
            except Exception:
                pass
            if not self._wait_topic_list():
                self.lg("⚠ 帖子列表加载超时（网络不佳？），跳过本板块")
                return []

        # 点击"回复"按钮进行排序
        self.lg("点击'回复'按钮进行排序...")
        try:
            sort_btn = self.pg.locator('th[data-sort-order="posts"] button')
            if sort_btn.count() > 0:
                sort_btn.first.click()
                self.lg("已点击回复排序按钮")
                # 排序会触发列表重渲染，等行元素稳定后再取数
                self._wait_topic_list(timeout_ms=15000)
                time.sleep(1.5)  # 等待排序完成
            else:
                self.lg("未找到回复排序按钮，使用默认排序")
        except Exception as e:
            self.lg("点击排序按钮失败，使用默认排序: " + str(e))

        # 优先获取未读话题（带小蓝点）
        topics = self.pg.evaluate(JS_GET_TOPICS)

        if topics:
            unread_count = len(topics.get("unread", []))
            read_count = len(topics.get("read", []))
            self.lg(f"找到 {unread_count} 个未读话题，{read_count} 个已读话题")

            # 优先返回未读话题，如果未读话题少于3个，补充一些已读话题
            unread = topics.get("unread", [])
            read = topics.get("read", [])

            if unread:
                self.lg(f"优先浏览 {len(unread)} 个未读话题")
                # 如果未读话题较少，可以补充一些已读话题
                if len(unread) < 3 and read:
                    self.lg(f"未读话题较少，补充 {min(3, len(read))} 个已读话题")
                    return unread + read[:3]
                return unread
            else:
                self.lg("没有未读话题，浏览已读话题")
                return read

        return []

    def get_floor_info(self):
        """获取楼层信息（当前楼层/总楼层）"""
        floor_info = self.pg.evaluate(JS_GET_FLOOR_INFO)
        return floor_info

    # ---------------- 爬楼 / 滚动 ----------------

    def scroll_page(self, duration=None, quick_mode=False):
        """爬楼模式 - 使用楼层计数器跟踪进度

        quick_mode: 快速浏览模式，只爬3-5层就返回
        返回值: 实际爬过的楼层数（结束楼层 - 开始楼层）
        """
        # 如果是快速浏览模式或者Bot设置为quick模式
        if quick_mode or self.browse_mode == "quick":
            return self._scroll_page_quick()

        # 获取初始楼层信息
        floor_info = self.get_floor_info()
        if not floor_info:
            self.lg("⚠ 无法获取楼层信息，使用传统滚动模式")
            # 降级到传统滚动模式
            self._scroll_page_legacy(duration)
            return 0

        total_floors = floor_info["total"]
        start_floor = floor_info["current"]  # 记录开始楼层
        self.lg(
            f"帖子总楼层数: {total_floors}，开始楼层: {start_floor} (来源: {floor_info.get('source', 'unknown')})"
        )

        if total_floors < 10:
            self.lg(f"楼层数太少（{total_floors}），使用快速浏览")
            self._scroll_page_legacy(duration)
            return max(0, total_floors - start_floor)

        scroll_count = 0
        current_floor = start_floor
        last_floor = start_floor
        stuck_count = 0  # 楼层卡住计数

        # 开始爬楼
        while current_floor < total_floors and self.run:
            # 检查是否达到目标（深度爬楼模式下实时检查）
            if self._check_target_reached():
                self.lg(f"已达到目标，停止爬楼")
                self.run = False
                break

            # 等待阅读（2-4秒，可被停止打断）
            self._wait_seconds(random.uniform(2, 4))

            # 滚动页面（600-1200px）
            scroll_distance = random.randint(600, 1200)
            self.pg.evaluate(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1

            # 等待页面更新
            self._wait_seconds(0.5)

            # 获取当前楼层
            floor_info = self.get_floor_info()
            if floor_info:
                current_floor = floor_info["current"]

                if current_floor > last_floor:
                    # 计算本次爬过的楼层数并累加到统计
                    floors_climbed = current_floor - last_floor
                    self.stats["floors"] += floors_climbed

                    self.lg(
                        f"爬楼 #{scroll_count} → 当前: {current_floor}/{total_floors} 楼 (本帖已爬 {current_floor - start_floor} 层)"
                    )
                    last_floor = current_floor
                    stuck_count = 0

                    # 实时更新进度和倒计时
                    if self.update_progress:
                        self.update_progress(self.stats)
                    self._update_countdown_display()
                else:
                    stuck_count += 1

                    # 如果楼层长时间不变，尝试更大的滚动
                    if stuck_count >= 3:
                        self.lg("楼层卡住，加大滚动距离")
                        self.pg.evaluate(f"window.scrollBy(0, 1500)")
                        self._wait_seconds(1)
                        stuck_count = 0

            # 安全检查：避免无限循环
            if scroll_count >= 200:
                self.lg("达到最大滚动次数，停止爬楼")
                break

        # 计算实际爬过的楼层数
        floors_climbed_total = current_floor - start_floor
        self.lg(
            f"爬楼完成: 滚动 {scroll_count} 次，从 {start_floor} 爬到 {current_floor}，共爬 {floors_climbed_total} 层"
        )
        return floors_climbed_total

    def _scroll_page_quick(self):
        """快速浏览模式 - 只爬3-5层就返回，用于增加浏览话题数量
        返回值: 实际爬过的楼层数（结束楼层 - 开始楼层）
        """
        floor_info = self.get_floor_info()
        if not floor_info:
            self.lg("⚠ 无法获取楼层信息，快速滚动3次")
            # 快速滚动3次，假设爬了3层
            for i in range(3):
                if not self.run:
                    break
                self._wait_seconds(random.uniform(1, 2))
                self.pg.evaluate(f"window.scrollBy(0, {random.randint(400, 800)})")
            self.stats["floors"] += 3
            if self.update_progress:
                self.update_progress(self.stats)
            self._update_countdown_display()
            return 3

        total_floors = floor_info["total"]
        start_floor = floor_info["current"]  # 记录开始楼层
        target_climb = random.randint(3, 5)  # 目标爬3-5层

        self.lg(
            f"[快速浏览] 开始楼层: {start_floor}，目标爬: {target_climb} 层 (总楼层: {total_floors})"
        )

        scroll_count = 0
        current_floor = start_floor
        last_floor = start_floor

        while (
            (current_floor - start_floor) < target_climb
            and current_floor < total_floors
            and self.run
        ):
            # 快速等待（1-2秒，可被停止打断）
            self._wait_seconds(random.uniform(1, 2))

            # 滚动页面
            scroll_distance = random.randint(400, 800)
            self.pg.evaluate(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1

            self._wait_seconds(0.3)

            # 获取当前楼层
            floor_info = self.get_floor_info()
            if floor_info:
                current_floor = floor_info["current"]
                if current_floor > last_floor:
                    # 计算本次爬过的楼层数并累加
                    floors_climbed = current_floor - last_floor
                    self.stats["floors"] += floors_climbed
                    last_floor = current_floor

                    # 实时更新进度和倒计时
                    if self.update_progress:
                        self.update_progress(self.stats)
                    self._update_countdown_display()

            # 安全检查
            if scroll_count >= 10:
                break

        floors_climbed_total = current_floor - start_floor
        self.lg(
            f"[快速浏览] 完成: 从 {start_floor} 爬到 {current_floor}，共爬 {floors_climbed_total} 层"
        )
        return floors_climbed_total

    def _scroll_page_legacy(self, duration=None):
        """传统滚动模式 - 用于无法获取楼层信息的情况"""
        if duration is None:
            duration = random.uniform(8, 15)

        self.lg(f"传统滚动模式 {duration:.1f}s...")
        start = time.time()
        while time.time() - start < duration and self.run:
            dist = random.randint(150, 400)
            self.pg.evaluate(f"window.scrollBy(0, {dist})")
            self._wait_seconds(random.uniform(1.0, 3.0))

            at_bottom = self.pg.evaluate(JS_AT_BOTTOM)
            if at_bottom:
                self._random_delay(1, 3, "阅读完毕")
                break
        return 0

    # ---------------- 点赞 / 回帖 ----------------

    def do_like(self, index=0):
        """点赞（index=0 主帖，>0 第 index 个回复）"""
        try:
            buttons = self.pg.locator("button.btn-toggle-reaction-like")
            count = buttons.count()
            if count <= index:
                self.lg(f"点赞按钮不足（共 {count} 个，需要 #{index + 1}）")
                return False

            btn = buttons.nth(index)
            cls = btn.get_attribute("class") or ""
            if "has-like" in cls or "my-likes" in cls:
                self.lg(f"帖子 #{index + 1} 已点赞，跳过")
                return False

            # 滚动到按钮位置后拟人点击（CloakBrowser humanize 会自动处理）
            try:
                btn.scroll_into_view_if_needed()
            except Exception:
                pass
            self._random_delay(0.3, 0.8, "移动到点赞按钮")
            btn.click()

            self._random_delay(0.8, 1.5, "点赞后")
            if index == 0:
                self.stats["like"] += 1
                self.lg("点赞主帖成功")
            else:
                self.stats["like_reply"] += 1
                self.lg(f"点赞回复 #{index} 成功")
            # 更新进度
            if self.update_progress:
                self.update_progress(self.stats)
            return True
        except Exception as e:
            self.lg("点赞失败: " + str(e))
        return False

    def do_reply(self, content=None):
        """回帖"""
        try:
            if content is None:
                content = random.choice(self.cfg["tpl"])

            self.lg("准备回复: " + content)

            # 点击回复按钮（打开编辑器）
            reply_btn = self.pg.locator(".topic-footer-main-buttons button.create")
            if reply_btn.count() == 0:
                self.lg("未找到回复按钮")
                return False
            reply_btn.first.click()

            self._random_delay(1.5, 3, "等待编辑器")

            # 输入内容（humanize 模式下为逐字符输入）
            editor = self.pg.locator("#reply-control textarea, .d-editor-input").first
            editor.fill(content)

            self._random_delay(0.8, 1.5, "输入内容后")

            # 提交
            submit_btn = self.pg.locator("#reply-control button.create").first
            submit_btn.click()

            self._random_delay(2, 4, "回复提交后")
            self.stats["reply"] += 1
            self.lg("回复成功")
            # 更新进度
            if self.update_progress:
                self.update_progress(self.stats)
            return True

        except Exception as e:
            self.lg("回复失败: " + str(e))
        return False

    # ---------------- 浏览帖子 ----------------

    def browse_topic(self, topic):
        """浏览帖子 - 通过点击链接而不是直接访问URL"""
        title = topic["title"]
        topic_id = topic.get("id", "")
        is_unread = topic.get("isUnread", False)

        if is_unread:
            self.lg("浏览未读话题: " + title)
        else:
            self.lg("浏览已读话题: " + title)

        try:
            # 关键修改：通过点击链接进入话题，而不是直接 get URL
            # 这样才能让"浏览话题"计数增加
            link = self.pg.locator(
                f'tr.topic-list-item[data-topic-id="{topic_id}"] a.title.raw-link.raw-topic-link'
            )
            if link.count() == 0:
                self.lg("未找到话题链接，跳过")
                return False
            link.first.click()

            # 等待页面加载
            self._random_delay(3, 5, "话题页面加载")

            # 等待帖子内容渲染（弱网下 SPA 渲染慢，楼层计时器可能还没出现）
            if not self._wait_topic_page():
                self.lg("⚠ 帖子内容加载较慢，继续尝试读取楼层信息")
            else:
                self.lg("话题页面已加载")

            self.stats["topic"] += 1

            # 更新进度
            if self.update_progress:
                self.update_progress(self.stats)

            # 更新倒计时
            self._update_countdown_display()

            # 爬楼阅读（scroll_page内部会实时更新stats["floors"]和进度）
            self.scroll_page()

            self._random_delay(1, 2, "阅读后")

            # 获取点赞按钮数量
            btn_count = self.pg.evaluate(JS_COUNT_LIKE_BUTTONS) or 0

            self.lg(f"找到 {btn_count} 个点赞按钮")

            # 随机点赞主帖（检查开关；达标停止后不再执行互动动作）
            if (
                self.run
                and self.enable_like
                and btn_count > 0
                and random.random() < self.cfg["like_rate"]
            ):
                self.do_like(0)
                if self.enable_wait:
                    self._random_delay(self.cfg["wait_min"], self.cfg["wait_max"], "点赞后休息")

            # 随机点赞回复（检查开关）
            if self.run and self.enable_like and btn_count > 1:
                for i in range(1, min(btn_count, 5)):
                    if not self.run:
                        break
                    if random.random() < self.cfg["like_reply_rate"]:
                        self.do_like(i)
                        if self.enable_wait:
                            self._random_delay(
                                self.cfg["wait_min"], self.cfg["wait_max"], "点赞回复后"
                            )

            # 随机回帖（检查开关）
            if self.run and self.enable_reply and random.random() < self.cfg["reply_rate"]:
                if self.enable_wait:
                    self._random_delay(self.cfg["wait_min"], self.cfg["wait_max"], "准备回帖")
                self.do_reply()

            # 关键修改：返回板块列表
            self.lg("返回板块列表...")
            self.pg.go_back()
            self._random_delay(2, 3, "返回后等待")

            # 如果是未读话题，检查小蓝点是否消失（确认已被标记为已读）
            if is_unread:
                badge_gone = self.pg.evaluate(f"""
                () => {{
                function checkBadgeGone() {{
                    const topicRow = document.querySelector('tr.topic-list-item[data-topic-id="{topic_id}"]');
                    if (!topicRow) {{
                        return true;  // 找不到行，可能已刷新
                    }}
                    // 检查小蓝点是否还存在
                    const badge = topicRow.querySelector('.badge.badge-notification.new-topic');
                    return !badge;  // 返回 true 表示小蓝点已消失
                }}
                return checkBadgeGone();
                }}
                """)

                if badge_gone:
                    self.lg("✓ 小蓝点已消失，话题已标记为已读")
                else:
                    self.lg("⚠ 小蓝点仍存在，可能需要更长浏览时间")

            return True
        except Exception as e:
            self.lg("浏览失败: " + str(e))
            # 失败时也尝试返回
            try:
                self.pg.go_back()
                time.sleep(1)
            except Exception:
                pass
            return False

    # ---------------- 倒计时 / 目标 ----------------

    def _update_countdown_display(self):
        """更新倒计时显示"""
        if not self.update_countdown or not self.start_time:
            return

        elapsed_time = time.time() - self.start_time
        elapsed_minutes = int(elapsed_time // 60)
        elapsed_seconds = int(elapsed_time % 60)
        # 超过 1 小时显示 H:MM:SS，否则 M:SS
        if elapsed_minutes >= 60:
            elapsed_str = f"{elapsed_time / 3600:.0f}:{elapsed_minutes % 60:02d}:{elapsed_seconds:02d}"
        else:
            elapsed_str = f"{elapsed_minutes}:{elapsed_seconds:02d}"

        # 根据浏览模式计算已读数
        if self.browse_mode == "quick":
            # 快速浏览模式：只计算主题数
            total_read = self.stats.get("topic", 0)
            read_desc = f"主题{total_read}"
        else:
            # 深度爬楼模式：计算主题+楼层
            topics = self.stats.get("topic", 0)
            floors = self.stats.get("floors", 0)
            total_read = topics + floors
            read_desc = f"帖{topics}+楼{floors}"

        if self.mode == "topics":
            remaining = self.target_value - total_read
            text = f"剩余: {remaining} | 已读: {total_read} ({read_desc}) | 用时: {elapsed_str}"
        elif self.mode == "time":
            elapsed_secs = elapsed_time
            remaining_secs = self.target_value * 60 - elapsed_secs
            if remaining_secs > 0:
                remaining_mins = int(remaining_secs / 60)
                remaining_s = int(remaining_secs % 60)
                text = f"剩余: {remaining_mins}:{remaining_s:02d} | 已读: {total_read} ({read_desc})"
            else:
                text = f"已超时 | 已读: {total_read} ({read_desc})"
        else:  # endless
            text = f"用时: {elapsed_str} | 已读: {total_read} ({read_desc})"

        self.update_countdown(text)

    def _check_target_reached(self):
        """检查是否达到目标，返回True表示应该停止"""
        if self.mode == "topics":
            if self.browse_mode == "quick":
                # 快速浏览模式：只计算主题数
                return self.stats.get("topic", 0) >= self.target_value
            else:
                # 深度爬楼模式：计算主题+楼层
                total_read = self.stats.get("topic", 0) + self.stats.get("floors", 0)
                return total_read >= self.target_value
        elif self.mode == "time":
            if self.start_time:
                elapsed_minutes = (time.time() - self.start_time) / 60
                return elapsed_minutes >= self.target_value
        return False

    # ---------------- 浏览板块 / 会话 ----------------

    def browse_cat(self, cat):
        """浏览板块"""
        # 先检查是否已达到目标
        if self._check_target_reached():
            return 0

        topics = self.get_topics(cat)
        self.lg(f"找到 {len(topics)} 个帖子")

        if not topics:
            return 0

        # 随机选择几个帖子
        count = min(random.randint(3, 8), len(topics))
        selected = random.sample(topics, count)

        browsed = 0
        for topic in selected:
            if not self.run:
                break

            # 检查是否已达到目标
            if self._check_target_reached():
                self.run = False
                break

            # 浏览话题（内部会自动返回板块列表）
            success = self.browse_topic(topic)
            if success:
                browsed += 1

            # 再次检查是否已达到目标
            if self._check_target_reached():
                self.run = False
                break

            # 防风控：帖子之间随机等待（检查开关）
            # 注意：browse_topic 返回时已经有等待，这里可以减少等待时间
            if self.run and self.enable_wait:
                self._random_delay(0.5, 1.5, "准备下一个话题")

        return browsed

    def run_session(self, username=None, password=None):
        """运行一次浏览会话

        username/password: 提供时先尝试自动登录（持久化 profile 已登录则跳过）；
                           不提供则等待用户在浏览器中手动登录（GUI 模式）。
        """
        self.run = True
        self.stats = {"topic": 0, "like": 0, "reply": 0, "like_reply": 0, "floors": 0}
        self.start_time = time.time()  # 记录开始时间

        if not self.start():
            return

        login_success = False

        try:
            if username and password:
                # 无头/Docker 模式：优先复用持久化登录态，失效则自动登录
                if not self._check_login():
                    if not self.login(username, password):
                        self.lg("登录失败，任务终止")
                        self.lg(
                            "常见原因：账号密码错误、Cloudflare 风控页拦截（服务器 IP 信誉差，"
                            "可配置 LINUXDO_PROXY 走代理）、或登录页改版"
                        )
                        return
                else:
                    self.lg("已存在有效登录状态（持久化 profile）")
                login_success = True
            else:
                # GUI 模式：等待用户手动登录
                if not self.check_login(wait_for_login=True, max_wait=300, check_interval=5):
                    self.lg("登录检查失败或超时，任务终止")
                    return
                login_success = True

            # 获取等级信息
            self.get_level_info()

            # 获取启用的板块
            enabled = [c for c in self.cats if c.get("e", True)]
            random.shuffle(enabled)

            # 显示运行模式
            if self.mode == "topics":
                self.lg("=" * 30)
                self.lg(f"运行模式: 帖子数量限制 (目标: {self.target_value} 个帖子)")
                self.lg("=" * 30)
            elif self.mode == "time":
                self.lg("=" * 30)
                self.lg(f"运行模式: 时间限制 (目标: {self.target_value} 分钟)")
                self.lg("=" * 30)
            else:
                self.lg("=" * 30)
                self.lg("运行模式: 无尽模式 (手动停止)")
                self.lg("=" * 30)

            # 显示功能开关状态
            features = []
            if self.enable_like:
                features.append("自动点赞")
            if self.enable_reply:
                features.append("自动回复")
            if self.enable_wait:
                features.append("等待延迟")
            self.lg(f"启用功能: {', '.join(features) if features else '仅浏览'}")

            self.lg(f"开始浏览 {len(enabled)} 个板块")
            self.lg("=" * 30)

            # 无尽循环板块
            while self.run:
                for cat in enabled:
                    if not self.run:
                        break

                    # 检查是否达到目标
                    if self._check_target_reached():
                        if self.browse_mode == "quick":
                            self.lg(
                                f"已达到目标主题数: {self.stats.get('topic', 0)}/{self.target_value}"
                            )
                        else:
                            total_read = self.stats.get("topic", 0) + self.stats.get(
                                "floors", 0
                            )
                            self.lg(
                                f"已达到目标已读数: {total_read}/{self.target_value} (帖子{self.stats['topic']}+爬楼{self.stats.get('floors', 0)})"
                            )
                        self.run = False
                        break

                    self.browse_cat(cat)

                    # 再次检查是否达到目标（browse_cat后可能已达到）
                    if self._check_target_reached():
                        if self.browse_mode == "quick":
                            self.lg(
                                f"已达到目标主题数: {self.stats.get('topic', 0)}/{self.target_value}"
                            )
                        else:
                            total_read = self.stats.get("topic", 0) + self.stats.get(
                                "floors", 0
                            )
                            self.lg(
                                f"已达到目标已读数: {total_read}/{self.target_value} (帖子{self.stats['topic']}+爬楼{self.stats.get('floors', 0)})"
                            )
                        self.run = False
                        break

                    # 显示进度
                    if self.browse_mode == "quick":
                        if self.mode == "topics":
                            remaining = self.target_value - self.stats.get("topic", 0)
                            self.lg(
                                f"📊 进度: {self.stats.get('topic', 0)}/{self.target_value} 主题 (剩余 {remaining})"
                            )
                    else:
                        total_read = self.stats.get("topic", 0) + self.stats.get("floors", 0)
                        if self.mode == "topics":
                            remaining = self.target_value - total_read
                            self.lg(
                                f"📊 进度: {total_read}/{self.target_value} (帖子{self.stats['topic']}+爬楼{self.stats.get('floors', 0)}) 剩余 {remaining}"
                            )

                    if self.mode == "time":
                        elapsed_minutes = (time.time() - self.start_time) / 60
                        remaining_minutes = self.target_value - elapsed_minutes
                        self.lg(
                            f"⏱ 进度: {int(elapsed_minutes)}/{self.target_value} 分钟 (剩余 {int(remaining_minutes)} 分钟)"
                        )

                    # 板块之间随机等待（检查开关）
                    if self.enable_wait and self.run:
                        self._random_delay(
                            self.cfg["wait_min"] + 1, self.cfg["wait_max"] + 2, "切换板块"
                        )

                # 如果不是无尽模式或已达到目标，退出循环
                if self.mode != "endless" or not self.run:
                    break

                # 无尽模式：重新打乱板块顺序
                if self.run:
                    random.shuffle(enabled)
                    self.lg("=" * 30)
                    self.lg("继续下一轮浏览...")
                    self.lg("=" * 30)

            # 计算耗时
            elapsed_time = time.time() - self.start_time
            elapsed_minutes = int(elapsed_time / 60)
            elapsed_seconds = int(elapsed_time % 60)

            # 计算已读总数
            total_read = self.stats.get("topic", 0) + self.stats.get("floors", 0)

            self.lg("=" * 30)
            self.lg("完成!")
            self.lg(f"浏览帖子: {self.stats['topic']}")
            self.lg(f"爬楼总数: {self.stats.get('floors', 0)} 楼")
            self.lg(f"已读总计: {total_read} (帖子+爬楼)")
            self.lg(f"点赞主帖: {self.stats['like']}")
            self.lg(f"点赞回复: {self.stats['like_reply']}")
            self.lg(f"回帖数量: {self.stats['reply']}")
            self.lg(f"耗时: {elapsed_minutes} 分 {elapsed_seconds} 秒")
            self.lg("=" * 30)

            # 重新获取等级信息以验证效果（在关闭浏览器前）
            if self.pg:
                self.lg("")
                self.lg("=" * 30)
                self.lg("重新获取等级信息验证效果...")
                final_info = self.get_level_info(is_final=True)

                # 显示真实进度变化
                if final_info and self.initial_level_info:
                    self.lg("")
                    self.lg("📊 真实进度变化（基于站点数据）:")
                    self.lg("-" * 30)
                    initial_reqs = {
                        r["name"]: r
                        for r in self.initial_level_info.get("requirements", [])
                    }
                    final_reqs = {
                        r["name"]: r for r in final_info.get("requirements", [])
                    }

                    for name, final_req in final_reqs.items():
                        if name in initial_reqs:
                            try:
                                initial_val = int(
                                    initial_reqs[name]["current"].replace(",", "")
                                )
                                final_val = int(final_req["current"].replace(",", ""))
                                change = final_val - initial_val
                                change_str = (
                                    f"+{change}" if change >= 0 else str(change)
                                )
                                self.lg(
                                    f"  {name}: {initial_val} → {final_val} ({change_str})"
                                )
                            except Exception:
                                self.lg(
                                    f"  {name}: {initial_reqs[name]['current']} → {final_req['current']}"
                                )
                    self.lg("-" * 30)

                self.lg("=" * 30)

        finally:
            self.run = False
            # 只有登录成功后才关闭浏览器，否则保留让用户查看
            if login_success:
                self.close()
