# -*- coding: utf-8 -*-
"""无头命令行版（Headless CLI）。

适用场景：
    - 服务器后台运行
    - GitHub Actions 定时任务
    - Docker

用法：
    python main.py cli -u 用户名 -p 密码
    python main.py cli -u 用户名 -p 密码 --target 50 --like-rate 20
    python main.py cli -u 用户名 -p 密码 --target 1h
    python main.py cli -u 用户名 -p 密码 --proxy 127.0.0.1:7897
    python main.py cli -u 用户名 -p 密码 --browse-mode quick

环境变量：
    LINUXDO_USERNAME  用户名
    LINUXDO_PASSWORD  密码
    LINUXDO_PROXY     代理地址（可选）
    LINUXDO_TARGET    运行目标（同 --target，默认 30min）

浏览器：
    基于 CloakBrowser（Playwright drop-in 隐身 Chromium）。
    首次运行会自动下载约 200MB 的浏览器内核；如需最新版本，
    可设置 CLOAKBROWSER_LICENSE_KEY（免费获取：cloakbrowser.dev/free
    或 python -m cloakbrowser login）。
"""

import os
import sys
from datetime import datetime

from . import __version__
from .bot import Bot, parse_target
from .config import CATS, DEFAULT_CONFIG


def _fix_stdout():
    """Windows 控制台默认 GBK 编码，无法输出 ⚠/📊 等 emoji，切换到 UTF-8"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


class Logger:
    """简单的日志工具"""

    def __init__(self, debug=False):
        self.debug_mode = debug

    def _timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def info(self, msg):
        print(f"[{self._timestamp()}] [INFO] {msg}")

    def success(self, msg):
        print(f"[{self._timestamp()}] [OK] {msg}")

    def warning(self, msg):
        print(f"[{self._timestamp()}] [WARN] {msg}")

    def error(self, msg):
        print(f"[{self._timestamp()}] [ERROR] {msg}")

    def debug(self, msg):
        if self.debug_mode:
            print(f"[{self._timestamp()}] [DEBUG] {msg}")


def parse_args(argv=None):
    """解析命令行参数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Linux.do 论坛自动浏览脚本（无头版 / CloakBrowser）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py cli -u myuser -p mypass                # 默认 30 分钟
  python main.py cli -u myuser -p mypass --target 50    # 浏览 50 个帖子
  python main.py cli -u myuser -p mypass --target 1h    # 运行 1 小时
  python main.py cli -u myuser -p mypass --proxy 127.0.0.1:7897

环境变量:
  LINUXDO_USERNAME  用户名
  LINUXDO_PASSWORD  密码
  LINUXDO_PROXY     代理地址（可选）
  LINUXDO_TARGET    运行目标（同 --target，默认 30min）
        """,
    )

    parser.add_argument(
        "-u",
        "--username",
        help="Linux.do 用户名（或设置环境变量 LINUXDO_USERNAME）",
    )
    parser.add_argument(
        "-p",
        "--password",
        help="Linux.do 密码（或设置环境变量 LINUXDO_PASSWORD）",
    )
    parser.add_argument("--proxy", help="代理地址，如 127.0.0.1:7897")
    parser.add_argument(
        "--target",
        "--topics",
        dest="target",
        default=None,
        help=(
            "运行目标：带时间单位=按时间运行（30min/1h/45分钟），"
            "纯数字=按帖子数量（30/50帖）；默认 30min（或环境变量 LINUXDO_TARGET）"
        ),
    )
    parser.add_argument(
        "--like-rate", type=int, default=30, help="点赞概率（0-100），默认 30"
    )
    parser.add_argument(
        "--browse-mode",
        choices=["deep", "quick"],
        default="deep",
        help="浏览模式：deep=深度爬楼（默认），quick=快速浏览（3-5层换帖）",
    )
    parser.add_argument(
        "--no-headless", action="store_true", help="禁用无头模式（显示浏览器窗口）"
    )
    parser.add_argument(
        "--no-humanize",
        action="store_true",
        help="禁用 CloakBrowser 拟人行为（默认开启）",
    )
    parser.add_argument(
        "--load-images",
        action="store_true",
        help="加载图片（默认禁用图片以降低流量和首屏时间，弱网推荐）",
    )
    parser.add_argument("--user-data-dir", help="用户数据目录（默认 ./browser_data）")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    return parser.parse_args(argv)


def main(argv=None):
    """主函数"""
    _fix_stdout()
    args = parse_args(argv)

    # 获取用户名和密码（优先命令行参数，其次环境变量）
    username = args.username or os.environ.get("LINUXDO_USERNAME")
    password = args.password or os.environ.get("LINUXDO_PASSWORD")
    proxy = args.proxy or os.environ.get("LINUXDO_PROXY")
    # 运行目标：命令行 > 环境变量 > 默认 30min
    target_str = args.target or os.environ.get("LINUXDO_TARGET") or "30min"

    # 验证必要参数
    if not username or not password:
        print("错误: 请提供用户名和密码")
        print()
        print("方式一: 命令行参数")
        print("  python main.py cli -u 用户名 -p 密码")
        print()
        print("方式二: 环境变量")
        print("  export LINUXDO_USERNAME='用户名'")
        print("  export LINUXDO_PASSWORD='密码'")
        print("  python main.py cli")
        sys.exit(1)

    # 创建日志工具
    logger = Logger(debug=args.debug)

    # 配置
    cfg = DEFAULT_CONFIG.copy()
    if proxy:
        cfg["proxy"] = proxy
    cfg["like_rate"] = args.like_rate / 100  # 转换为小数
    cfg["block_images"] = not args.load_images

    # 解析运行目标："30"=30帖，"30min"=30分钟，"1h"=1小时，识别不了走默认 30min
    mode, target_value = parse_target(target_str)

    # 创建机器人并运行
    bot = Bot(
        cfg,
        CATS,
        logger.info,
        mode=mode,
        target_value=target_value,
        enable_like=True,
        enable_reply=False,  # 无头版默认不自动回帖（避免被检测）
        enable_wait=True,
        browse_mode=args.browse_mode,
        headless=not args.no_headless,
        humanize=not args.no_humanize,
        block_images=not args.load_images,
        user_data_dir=args.user_data_dir,
    )

    logger.info(f"Linux.do 自动浏览任务开始 (v{__version__}, CloakBrowser)")
    if mode == "topics":
        logger.info(f"目标: 浏览 {target_value} 个帖子，浏览模式: {args.browse_mode}")
    else:
        logger.info(f"目标: 运行 {target_value:g} 分钟，浏览模式: {args.browse_mode}")

    try:
        bot.run_session(username=username, password=password)
    finally:
        # 确保浏览器进程被回收
        bot.close()

    # 返回状态码
    sys.exit(0 if bot.stats["topic"] > 0 else 1)


if __name__ == "__main__":
    main()
