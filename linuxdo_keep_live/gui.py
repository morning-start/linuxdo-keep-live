# -*- coding: utf-8 -*-
"""图形界面版（Tkinter GUI）。

功能：
    1. 自动获取用户等级和升级进度
    2. 多板块浏览
    3. 随机点赞帖子和回复
    4. 随机回帖（默认关闭，开启时有风险提醒）
    5. 统计报告
    6. 防风控机制（随机间隔）
    7. 升级进度实时追踪
    8. 系统托盘支持（需 pystray + Pillow，可选安装）
    9. 快速浏览模式（增加浏览话题数）
    10. 真实进度变化统计

浏览器引擎为 CloakBrowser（Playwright drop-in 隐身 Chromium）。
"""

import os
import random
import sys
import threading
import time
from datetime import datetime

# Linux 输入法兼容性修复（必须在导入 tkinter 之前设置）
import platform

if platform.system() == "Linux":
    # 尝试检测并设置输入法环境变量
    if "GTK_IM_MODULE" not in os.environ:
        # 检测 fcitx
        if os.path.exists("/usr/bin/fcitx") or os.path.exists("/usr/bin/fcitx5"):
            os.environ["GTK_IM_MODULE"] = "fcitx"
            os.environ["QT_IM_MODULE"] = "fcitx"
            os.environ["XMODIFIERS"] = "@im=fcitx"
        # 检测 ibus
        elif os.path.exists("/usr/bin/ibus"):
            os.environ["GTK_IM_MODULE"] = "ibus"
            os.environ["QT_IM_MODULE"] = "ibus"
            os.environ["XMODIFIERS"] = "@im=ibus"

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from . import __version__, APP_NAME
from .bot import Bot
from .config import CATS, DEFAULT_CONFIG

# 跨平台字体配置
if platform.system() == "Darwin":  # macOS
    FONT_FAMILY = "PingFang SC"
    FONT_MONO = "Menlo"
elif platform.system() == "Linux":
    FONT_FAMILY = "Noto Sans CJK SC"
    FONT_MONO = "Monospace"
else:  # Windows
    FONT_FAMILY = "Microsoft YaHei UI"
    FONT_MONO = "Consolas"

# 托盘支持（macOS 上禁用，因为可能导致 UI 问题；依赖缺失时自动降级）
TRAY_SUPPORT = False
if platform.system() != "Darwin":  # 非 macOS
    try:
        import pystray
        from PIL import Image, ImageDraw

        TRAY_SUPPORT = True
    except ImportError:
        TRAY_SUPPORT = False
else:
    # macOS 上尝试导入 PIL（用于其他功能），但禁用托盘
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        pass


def get_icon_path():
    """获取图标路径（可选，不存在时跳过）"""
    if getattr(sys, "frozen", False):
        # 打包后的路径
        base_path = sys._MEIPASS
    else:
        # 开发环境路径
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, "icon.ico")


def create_tray_image(color="#0f3460"):
    """创建托盘图标图像"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景圆形
    padding = 4
    draw.ellipse([padding, padding, size - padding, size - padding], fill=color)

    # 内圈
    inner_padding = 12
    draw.ellipse(
        [inner_padding, inner_padding, size - inner_padding, size - inner_padding],
        fill="#1a1a2e",
    )

    # 中心点
    center = size // 2
    dot_size = 8
    draw.ellipse(
        [center - dot_size, center - dot_size, center + dot_size, center + dot_size],
        fill="#00d9ff",
    )

    return img


VERSION = __version__


class GUI:
    def __init__(s):
        s.rt = tk.Tk()
        s.rt.title(f"{APP_NAME} v{VERSION} (CloakBrowser)")
        s.rt.geometry("700x950")
        s.rt.minsize(650, 850)  # 设置最小窗口大小
        s.rt.configure(bg="#1a1a2e")

        # 设置窗口图标
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                s.rt.iconbitmap(icon_path)
        except Exception:
            pass

        # 不使用overrideredirect，保留系统标题栏以支持窗口拉伸
        # s.rt.overrideredirect(True)  # 移除默认标题栏

        s.cats = [c.copy() for c in CATS]
        s.cfg = DEFAULT_CONFIG.copy()
        s.bot = None
        s.th = None
        s.req_labels = {}  # 升级要求标签
        s.initial_requirements = []  # 初始升级要求

        # 窗口拖动相关（保留以备后用）
        s._drag_x = 0
        s._drag_y = 0

        # 托盘相关
        s.tray_icon = None
        s.tray_thread = None
        s._running_status = "就绪"

        s._ui()

        # 窗口居中
        s._center_window()

        # 初始化托盘
        if TRAY_SUPPORT:
            s._init_tray()

        # 窗口关闭时的处理
        s.rt.protocol("WM_DELETE_WINDOW", s._on_close_window)

    # ---------------- 托盘 ----------------

    def _init_tray(s):
        """初始化系统托盘"""
        if not TRAY_SUPPORT:
            return

        def create_menu():
            return pystray.Menu(
                pystray.MenuItem("显示窗口", s._show_window, default=True),
                pystray.MenuItem("开始运行", s._tray_start),
                pystray.MenuItem("停止运行", s._tray_stop),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", s._tray_quit),
            )

        # 创建托盘图标
        s.tray_icon = pystray.Icon(
            "LinuxDoHelper",
            create_tray_image("#0f3460"),
            f"{APP_NAME} - 就绪",
            create_menu(),
        )

        # 在后台线程运行托盘
        s.tray_thread = threading.Thread(target=s.tray_icon.run, daemon=True)
        s.tray_thread.start()

    def _update_tray_status(s, status, stats=None):
        """更新托盘状态"""
        if not TRAY_SUPPORT or not s.tray_icon:
            return

        s._running_status = status

        # 根据状态设置不同颜色
        if status == "运行中":
            color = "#00ff88"  # 绿色
        elif status == "已停止" or status == "已完成":
            color = "#ffaa00"  # 橙色
        else:
            color = "#0f3460"  # 默认蓝色

        # 更新图标
        s.tray_icon.icon = create_tray_image(color)

        # 更新提示文字
        tooltip = f"{APP_NAME} v{VERSION} - {status}\n"

        if s.bot and s.bot.start_time:
            # 计算用时
            elapsed_time = time.time() - s.bot.start_time
            elapsed_minutes = int(elapsed_time / 60)
            elapsed_seconds = int(elapsed_time % 60)

            # 计算已读总数
            total_read = s.bot.stats.get("topic", 0) + s.bot.stats.get("floors", 0)

            # 显示模式
            if s.bot.mode == "topics":
                remaining = s.bot.target_value - total_read
                tooltip += f"模式: 已读限制 (剩余 {remaining}/{s.bot.target_value})\n"
            elif s.bot.mode == "time":
                elapsed_mins = elapsed_time / 60
                remaining_mins = s.bot.target_value - elapsed_mins
                tooltip += f"模式: 时间限制 (剩余 {int(remaining_mins)}/{s.bot.target_value}分钟)\n"
            else:
                tooltip += f"模式: 无尽模式\n"

            # 显示浏览模式
            if s.bot.browse_mode == "quick":
                tooltip += f"浏览: 快速模式\n"
            else:
                tooltip += f"浏览: 深度爬楼\n"

            tooltip += f"用时: {elapsed_minutes}:{elapsed_seconds:02d}\n"

        if stats:
            total_read = stats.get("topic", 0) + stats.get("floors", 0)
            tooltip += f"已读: {total_read} (帖{stats.get('topic', 0)}+楼{stats.get('floors', 0)}) | "
            tooltip += f"点赞: {stats.get('like', 0) + stats.get('like_reply', 0)} | "
            tooltip += f"回复: {stats.get('reply', 0)}"

        s.tray_icon.title = tooltip

    def _show_window(s, icon=None, item=None):
        """显示窗口"""
        s.rt.after(0, s._do_show_window)

    def _do_show_window(s):
        """在主线程中显示窗口"""
        s.rt.deiconify()
        s.rt.lift()
        s.rt.focus_force()

    def _tray_start(s, icon=None, item=None):
        """从托盘启动"""
        s.rt.after(0, s._start)

    def _tray_stop(s, icon=None, item=None):
        """从托盘停止"""
        s.rt.after(0, s._stop)

    def _tray_quit(s, icon=None, item=None):
        """从托盘退出"""
        if s.tray_icon:
            s.tray_icon.stop()
        s.rt.after(0, s._close)

    def _on_close_window(s):
        """窗口关闭按钮处理 - 最小化到托盘"""
        if TRAY_SUPPORT and s.tray_icon:
            s.rt.withdraw()  # 隐藏窗口
        else:
            s._close()

    # ---------------- 窗口工具 ----------------

    def _center_window(s):
        """窗口居中显示"""
        s.rt.update_idletasks()
        w = s.rt.winfo_width()
        h = s.rt.winfo_height()
        sw = s.rt.winfo_screenwidth()
        sh = s.rt.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        s.rt.geometry(f"{w}x{h}+{x}+{y}")

    def _start_drag(s, event):
        """开始拖动窗口"""
        s._drag_x = event.x
        s._drag_y = event.y

    def _do_drag(s, event):
        """拖动窗口"""
        x = s.rt.winfo_x() + event.x - s._drag_x
        y = s.rt.winfo_y() + event.y - s._drag_y
        s.rt.geometry(f"+{x}+{y}")

    def _minimize(s):
        """最小化窗口"""
        if TRAY_SUPPORT and s.tray_icon:
            s.rt.withdraw()  # 最小化到托盘
        else:
            s.rt.iconify()

    def _on_restore(s, event):
        """恢复窗口"""
        pass  # 不再需要overrideredirect

    def _close(s):
        """关闭窗口"""
        if s.bot:
            s.bot.stop()
        if s.tray_icon:
            try:
                s.tray_icon.stop()
            except Exception:
                pass
        s.rt.destroy()

    # ---------------- 界面 ----------------

    def _ui(s):
        # 状态变量（放在顶部，供其他地方使用）
        s.status = tk.StringVar(value="就绪")

        # 内容区域
        content = tk.Frame(s.rt, bg="#1a1a2e")
        content.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # 用户信息栏
        info_frame = tk.LabelFrame(
            content,
            text=" 用户信息 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        info_frame.pack(fill=tk.X, padx=15, pady=5)

        info_inner = tk.Frame(info_frame, bg="#1a1a2e")
        info_inner.pack(fill=tk.X, padx=10, pady=5)

        s.user_label = tk.StringVar(value="用户: 未登录")
        s.level_label = tk.StringVar(value="等级: -")
        s.next_level_label = tk.StringVar(value="下一级: -")

        tk.Label(
            info_inner,
            textvariable=s.user_label,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            info_inner,
            textvariable=s.level_label,
            bg="#1a1a2e",
            fg="#00ff88",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            info_inner,
            textvariable=s.next_level_label,
            bg="#1a1a2e",
            fg="#ffaa00",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)

        # 升级进度面板（使用固定高度的Canvas实现滚动）
        progress_frame = tk.LabelFrame(
            content,
            text=" 升级进度追踪 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        progress_frame.pack(fill=tk.X, padx=15, pady=5)

        # 创建Canvas和滚动条
        s.progress_canvas = tk.Canvas(
            progress_frame, bg="#1a1a2e", height=200, highlightthickness=0
        )
        s.progress_scrollbar = ttk.Scrollbar(
            progress_frame, orient="vertical", command=s.progress_canvas.yview
        )
        s.progress_inner = tk.Frame(s.progress_canvas, bg="#1a1a2e")

        s.progress_inner.bind(
            "<Configure>",
            lambda e: s.progress_canvas.configure(
                scrollregion=s.progress_canvas.bbox("all")
            ),
        )

        s.progress_canvas.create_window((0, 0), window=s.progress_inner, anchor="nw")
        s.progress_canvas.configure(yscrollcommand=s.progress_scrollbar.set)

        s.progress_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        s.progress_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        # 运行模式选择
        mode_frame = tk.LabelFrame(
            content,
            text=" 运行模式 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        mode_frame.pack(fill=tk.X, padx=15, pady=5)

        mode_inner = tk.Frame(mode_frame, bg="#1a1a2e")
        mode_inner.pack(fill=tk.X, padx=10, pady=8)

        s.mode_var = tk.StringVar(value="endless")

        # 无尽模式
        tk.Radiobutton(
            mode_inner,
            text="无尽模式",
            variable=s.mode_var,
            value="endless",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        # 帖子数量模式
        tk.Radiobutton(
            mode_inner,
            text="帖子数量:",
            variable=s.mode_var,
            value="topics",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        s.topics_var = tk.StringVar(value="50")
        tk.Entry(
            mode_inner,
            textvariable=s.topics_var,
            width=8,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(
            mode_inner,
            text="个",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

        # 时间限制模式
        tk.Radiobutton(
            mode_inner,
            text="时间限制:",
            variable=s.mode_var,
            value="time",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        s.time_var = tk.StringVar(value="30")
        tk.Entry(
            mode_inner,
            textvariable=s.time_var,
            width=8,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(
            mode_inner,
            text="分钟",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

        # 浏览模式选择（第二行）
        browse_mode_inner = tk.Frame(mode_frame, bg="#1a1a2e")
        browse_mode_inner.pack(fill=tk.X, padx=10, pady=(0, 8))

        tk.Label(
            browse_mode_inner,
            text="浏览模式:",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=(0, 10))

        s.browse_mode_var = tk.StringVar(value="deep")

        tk.Radiobutton(
            browse_mode_inner,
            text="深度爬楼（完整阅读）",
            variable=s.browse_mode_var,
            value="deep",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=5)

        tk.Radiobutton(
            browse_mode_inner,
            text="快速浏览（3-5层换帖）",
            variable=s.browse_mode_var,
            value="quick",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(
            browse_mode_inner,
            text="(快速模式增加浏览话题数)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT, padx=5)

        # 控制栏
        ctrl = tk.Frame(content, bg="#1a1a2e", pady=5)
        ctrl.pack(fill=tk.X, padx=15)
        tk.Label(ctrl, text="代理(可空):", bg="#1a1a2e", fg="#eaeaea").pack(side=tk.LEFT)
        s.proxy_var = tk.StringVar(value=s.cfg["proxy"])
        tk.Entry(
            ctrl,
            textvariable=s.proxy_var,
            width=18,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=5)

        s.start_btn = tk.Button(
            ctrl,
            text="开始",
            command=s._start,
            width=10,
            bg="#0f3460",
            fg="white",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.start_btn.pack(side=tk.LEFT, padx=10)
        s.stop_btn = tk.Button(
            ctrl,
            text="停止",
            command=s._stop,
            width=8,
            bg="#e94560",
            fg="white",
            state=tk.DISABLED,
        )
        s.stop_btn.pack(side=tk.LEFT)

        # 倒计时/倒计数显示
        s.countdown_var = tk.StringVar(value="")
        s.countdown_label = tk.Label(
            ctrl,
            textvariable=s.countdown_var,
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.countdown_label.pack(side=tk.LEFT, padx=15)

        # 主区域
        main = tk.Frame(content, bg="#1a1a2e")
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # 左侧 - 板块选择
        left = tk.LabelFrame(
            main,
            text=" 板块选择 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        s.cat_vars = {}
        for cat in s.cats:
            var = tk.BooleanVar(value=cat.get("e", True))
            s.cat_vars[cat["n"]] = var
            cb = tk.Checkbutton(
                left,
                text=cat["n"],
                variable=var,
                bg="#1a1a2e",
                fg="#eaeaea",
                selectcolor="#0f3460",
                activebackground="#1a1a2e",
                command=lambda n=cat["n"], v=var: s._toggle_cat(n, v),
            )
            cb.pack(anchor=tk.W, pady=1)

        # 右侧
        right = tk.Frame(main, bg="#1a1a2e")
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 日志区域
        tk.Label(
            right,
            text="运行日志",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(anchor=tk.W)
        s.log = scrolledtext.ScrolledText(
            right,
            height=14,
            bg="#16213e",
            fg="#eaeaea",
            font=(FONT_MONO, 9),
            insertbackground="#eaeaea",
        )
        s.log.pack(fill=tk.BOTH, expand=True, pady=5)
        s.log.config(state=tk.DISABLED)

        # 参数设置
        param = tk.Frame(right, bg="#1a1a2e")
        param.pack(fill=tk.X, pady=5)

        # 第一行：点赞率和回复率
        param_row1 = tk.Frame(param, bg="#1a1a2e")
        param_row1.pack(fill=tk.X, pady=2)

        # 自动点赞开关（默认关闭）
        s.enable_like_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            param_row1,
            text="自动点赞",
            variable=s.enable_like_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row1, text="点赞率:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.like_var = tk.StringVar(value="30")
        tk.Entry(
            param_row1, textvariable=s.like_var, width=4, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row1, text="%", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(0, 15)
        )

        # 自动回复开关（默认关闭）
        s.enable_reply_var = tk.BooleanVar(value=False)
        s.reply_checkbox = tk.Checkbutton(
            param_row1,
            text="自动回复",
            variable=s.enable_reply_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
            command=s._on_reply_toggle,
        )
        s.reply_checkbox.pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row1, text="回复率:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.reply_var = tk.StringVar(value="5")
        tk.Entry(
            param_row1, textvariable=s.reply_var, width=4, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row1, text="%", bg="#1a1a2e", fg="#eaeaea").pack(side=tk.LEFT)

        # 第二行：等待时间 + 图片开关
        param_row2 = tk.Frame(param, bg="#1a1a2e")
        param_row2.pack(fill=tk.X, pady=2)

        # 禁用图片开关（默认开启，弱网提速）
        s.block_images_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            param_row2,
            text="禁用图片",
            variable=s.block_images_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))

        # 等待时间开关
        s.enable_wait_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            param_row2,
            text="启用等待",
            variable=s.enable_wait_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row2, text="等待:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.wait_var = tk.StringVar(value="1-3")
        tk.Entry(
            param_row2, textvariable=s.wait_var, width=6, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row2, text="秒", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        tk.Label(
            param_row2,
            text="(已有滚动延迟，可关闭)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

        # 统计信息
        stats_frame = tk.LabelFrame(
            right,
            text=" 本次统计 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        stats_frame.pack(fill=tk.X, pady=5)

        stats_inner = tk.Frame(stats_frame, bg="#1a1a2e")
        stats_inner.pack(fill=tk.X, padx=10, pady=5)

        s.stats_topic = tk.StringVar(value="帖子: 0")
        s.stats_floors = tk.StringVar(value="爬楼: 0")
        s.stats_total = tk.StringVar(value="已读: 0")
        s.stats_like = tk.StringVar(value="点赞: 0")
        s.stats_reply = tk.StringVar(value="回复: 0")

        tk.Label(
            stats_inner,
            textvariable=s.stats_topic,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_floors,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_total,
            bg="#1a1a2e",
            fg="#00ff88",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_like,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_reply,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)

    def _toggle_cat(s, name, var):
        for cat in s.cats:
            if cat["n"] == name:
                cat["e"] = var.get()
                break

    def _on_reply_toggle(s):
        """自动回复开关切换时的处理"""
        if s.enable_reply_var.get():
            # 用户启用了自动回复，显示风险提醒
            result = messagebox.askokcancel(
                "风险提醒",
                "⚠️ 自动回复功能风险提示\n\n"
                "据社区反馈，L站可能存在检测自动回复的机制：\n"
                "• 曾有用户因自动回复被举报\n"
                "• 可能影响账号信任等级\n"
                "• 建议仅在必要时谨慎使用\n\n"
                "是否确定要启用自动回复功能？",
                icon="warning",
            )
            if not result:
                # 用户取消，恢复为未选中状态
                s.enable_reply_var.set(False)

    # ---------------- 进度 / 信息更新 ----------------

    def _update_info(s, info, is_final=False):
        """更新用户信息显示"""

        def update():
            if info.get("username"):
                s.user_label.set("用户: " + info["username"])
            if info.get("level"):
                s.level_label.set("等级: " + info["level"] + "级")
            if info.get("nextLevel"):
                s.next_level_label.set("下一级: " + info["nextLevel"] + "级")

            # 更新升级进度面板
            requirements = info.get("requirements", [])
            if requirements:
                if not s.initial_requirements:
                    # 首次获取，保存初始值
                    s.initial_requirements = requirements.copy()
                    s._build_progress_panel(requirements)
                elif is_final:
                    # 结束时更新，显示实际变化
                    s._update_final_progress(requirements)

        s.rt.after(0, update)

    def _update_final_progress(s, new_requirements):
        """结束时更新进度面板，显示实际变化"""
        for new_req in new_requirements:
            name = new_req.get("name", "")
            new_current = new_req.get("current", "0")

            if name in s.req_labels:
                labels = s.req_labels[name]
                try:
                    initial = int(labels["initial"].replace(",", ""))
                    new_val = int(new_current.replace(",", ""))
                    actual_added = new_val - initial

                    labels["current_var"].set(new_current)
                    if actual_added > 0:
                        labels["added_var"].set(f"+{actual_added}")
                    elif actual_added < 0:
                        labels["added_var"].set(str(actual_added))
                    else:
                        labels["added_var"].set("+0")
                except Exception:
                    labels["current_var"].set(new_current)

    def _build_progress_panel(s, requirements):
        """构建升级进度面板"""
        # 清除旧内容
        for widget in s.progress_inner.winfo_children():
            widget.destroy()
        s.req_labels = {}

        # 创建表格头
        headers = ["指标", "初始值", "当前值", "目标值", "本次+"]
        # 列宽设置为0表示自动适应内容宽度
        col_widths = [0, 0, 0, 0, 0]
        # 每列的左右间距 (padx)
        col_padx = [(10, 20), (10, 20), (10, 15), (10, 15), (10, 10)]

        for col, header in enumerate(headers):
            tk.Label(
                s.progress_inner,
                text=header,
                bg="#1a1a2e",
                fg="#00d9ff",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=0, column=col, padx=col_padx[col], pady=5, sticky="w")

        # 创建数据行
        for row, req in enumerate(requirements[:8], start=1):
            name = req.get("name", "")
            current = req.get("current", "0")
            required = req.get("required", "0")

            # 指标名
            tk.Label(
                s.progress_inner,
                text=name,
                bg="#1a1a2e",
                fg="#eaeaea",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=0, padx=col_padx[0], pady=3, sticky="w")

            # 初始值
            tk.Label(
                s.progress_inner,
                text=current,
                bg="#1a1a2e",
                fg="#888888",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=1, padx=col_padx[1], pady=3, sticky="w")

            # 当前值（可更新）
            current_var = tk.StringVar(value=current)
            tk.Label(
                s.progress_inner,
                textvariable=current_var,
                bg="#1a1a2e",
                fg="#00ff88",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=row, column=2, padx=col_padx[2], pady=3, sticky="w")

            # 目标值
            tk.Label(
                s.progress_inner,
                text=required,
                bg="#1a1a2e",
                fg="#ffaa00",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=3, padx=col_padx[3], pady=3, sticky="w")

            # 本次增加
            added_var = tk.StringVar(value="+0")
            tk.Label(
                s.progress_inner,
                textvariable=added_var,
                bg="#1a1a2e",
                fg="#00d9ff",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=row, column=4, padx=col_padx[4], pady=3, sticky="w")

            # 保存引用
            s.req_labels[name] = {
                "initial": current,
                "current_var": current_var,
                "added_var": added_var,
            }

    def _update_progress(s, stats):
        """根据统计更新进度显示"""

        def update():
            if not s.req_labels:
                return

            # 根据统计数据更新相关指标
            for name, labels in s.req_labels.items():
                try:
                    initial = int(labels["initial"].replace(",", ""))
                    added = 0

                    # 根据指标名匹配统计
                    if "浏览" in name or "阅读" in name or "话题" in name:
                        added = stats.get("topic", 0)
                    elif "点赞" in name or "赞" in name:
                        added = stats.get("like", 0) + stats.get("like_reply", 0)
                    elif "回复" in name or "发帖" in name:
                        added = stats.get("reply", 0)

                    if added > 0:
                        new_val = initial + added
                        labels["current_var"].set(str(new_val))
                        labels["added_var"].set(f"+{added}")
                except Exception:
                    pass

            # 更新托盘状态（实时显示统计）
            s._update_tray_status("运行中", stats)

        s.rt.after(0, update)

    def _update_countdown(s, text):
        """更新倒计时显示"""

        def update():
            s.countdown_var.set(text)

        s.rt.after(0, update)

    def _lg(s, msg):
        def log():
            ts = datetime.now().strftime("%H:%M:%S")
            s.log.config(state=tk.NORMAL)
            s.log.insert(tk.END, "[" + ts + "] " + msg + "\n")
            s.log.see(tk.END)
            s.log.config(state=tk.DISABLED)

            # 更新统计
            if s.bot:
                topics = s.bot.stats.get("topic", 0)
                floors = s.bot.stats.get("floors", 0)
                total_read = topics + floors
                s.stats_topic.set(f"帖子: {topics}")
                s.stats_floors.set(f"爬楼: {floors}")
                s.stats_total.set(f"已读: {total_read}")
                s.stats_like.set(
                    f"点赞: {s.bot.stats['like'] + s.bot.stats['like_reply']}"
                )
                s.stats_reply.set(f"回复: {s.bot.stats['reply']}")

        s.rt.after(0, log)

    # ---------------- 运行控制 ----------------

    def _start(s):
        if s.th and s.th.is_alive():
            return
        # 更新配置
        s.cfg["proxy"] = s.proxy_var.get()
        try:
            s.cfg["like_rate"] = int(s.like_var.get()) / 100
        except Exception:
            s.cfg["like_rate"] = 0.3
        try:
            s.cfg["reply_rate"] = int(s.reply_var.get()) / 100
        except Exception:
            s.cfg["reply_rate"] = 0.05
        try:
            parts = s.wait_var.get().split("-")
            s.cfg["wait_min"] = float(parts[0])
            s.cfg["wait_max"] = float(parts[1]) if len(parts) > 1 else float(parts[0])
        except Exception:
            s.cfg["wait_min"], s.cfg["wait_max"] = 1, 3

        s.start_btn.config(state=tk.DISABLED)
        s.stop_btn.config(state=tk.NORMAL)
        s.status.set("运行中...")

        # 更新托盘状态
        s._update_tray_status("运行中")

        # 重置初始数据
        s.initial_requirements = []

        # 读取运行模式设置
        mode = s.mode_var.get()
        target_value = 0

        if mode == "topics":
            try:
                target_value = int(s.topics_var.get())
            except Exception:
                target_value = 50
        elif mode == "time":
            try:
                target_value = int(s.time_var.get())
            except Exception:
                target_value = 30

        # 读取开关状态
        enable_like = s.enable_like_var.get()
        enable_reply = s.enable_reply_var.get()
        enable_wait = s.enable_wait_var.get()
        browse_mode = s.browse_mode_var.get()
        block_images = s.block_images_var.get()
        s.cfg["block_images"] = block_images

        s.bot = Bot(
            s.cfg,
            s.cats,
            s._lg,
            s._update_info,
            s._update_progress,
            s._update_countdown,
            mode=mode,
            target_value=target_value,
            enable_like=enable_like,
            enable_reply=enable_reply,
            enable_wait=enable_wait,
            browse_mode=browse_mode,
            headless=False,  # GUI 模式显示浏览器，便于手动登录
            block_images=block_images,
        )
        s.th = threading.Thread(target=s._run, daemon=True)
        s.th.start()

    def _run(s):
        try:
            s.bot.run_session()
        finally:
            s.rt.after(0, s._done)

    def _done(s):
        s.start_btn.config(state=tk.NORMAL)
        s.stop_btn.config(state=tk.DISABLED)
        s.status.set("已完成")

        # 更新托盘状态
        if s.bot:
            s._update_tray_status("已完成", s.bot.stats)
        else:
            s._update_tray_status("已完成")

    def _stop(s):
        if s.bot:
            s.bot.stop()
        s.status.set("正在停止...")
        s._update_tray_status("已停止")

    def run(s):
        s.rt.mainloop()


def main():
    GUI().run()


if __name__ == "__main__":
    main()
