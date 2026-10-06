# -*- coding: utf-8 -*-
"""Docker / 服务器常驻版：真实浏览器 + 随机定时调度。

对应参考项目的 docker/linux_do_docker.py，改造点：
    - 浏览器操作复用核心 Bot（CloakBrowser），不再单独维护一套 DrissionPage 逻辑
    - 保留 RandomScheduler（每天随机生成 N 个运行时间点，模拟真人使用习惯）

用法：
    python main.py docker -u 用户名 -p 密码
    python main.py docker -u 用户名 -p 密码 --runs-per-day 2 --topics-min 15 --topics-max 40
    python main.py docker -u 用户名 -p 密码 --once

环境变量：
    LINUXDO_USERNAME  用户名
    LINUXDO_PASSWORD  密码
    LINUXDO_PROXY     代理地址（可选）
    LIKE_RATE         点赞概率（0-100，默认 30）
    RUNS_PER_DAY      每天运行次数（默认 2）
    TOPICS_MIN        每次最少浏览帖子数（默认 15）
    TOPICS_MAX        每次最多浏览帖子数（默认 40）
    CHROME_USER_DATA  用户数据目录（默认 ./browser_data）
    RUN_ON_START      首次启动是否立即运行一次（默认 true）
    DEBUG             调试日志
"""

import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta

from . import __version__
from .bot import Bot
from .config import CATS, DEFAULT_CONFIG

# 每次任务的帖子数范围（分钟级随机，模拟真人使用习惯）
DEFAULT_TOPICS_RANGE = (15, 40)

# 随机运行时间段（每天 7:00 - 23:00 之间随机取点，含 22:59）
SCHEDULE_HOUR_RANGE = (7, 22)


class Log:
    """日志工具（Docker 环境输出到 stdout，flush 保证日志顺序）"""

    def __init__(self, debug=False):
        self.debug_mode = debug
        # Windows 控制台默认 GBK 编码，无法输出 ⚠/📊 等 emoji，切换到 UTF-8
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8")
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _ts():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def info(self, msg):
        print(f"[{Log._ts()}] [INFO] {msg}", flush=True)

    def ok(self, msg):
        print(f"[{Log._ts()}] [OK] {msg}", flush=True)

    def warn(self, msg):
        print(f"[{Log._ts()}] [WARN] {msg}", flush=True)

    def err(self, msg):
        print(f"[{Log._ts()}] [ERROR] {msg}", flush=True)

    def debug(self, msg):
        if self.debug_mode:
            print(f"[{Log._ts()}] [DEBUG] {msg}", flush=True)


class DockerBot:
    """Docker 版浏览任务：每次运行浏览随机数量的帖子（复用核心 Bot）"""

    def __init__(
        self,
        username,
        password,
        like_rate=0.3,
        topics_range=DEFAULT_TOPICS_RANGE,
        proxy=None,
        headless=True,
        block_images=True,
        user_data_dir=None,
        logger=None,
    ):
        self.username = username
        self.password = password
        self.like_rate = like_rate
        self.topics_range = topics_range
        self.proxy = proxy
        self.headless = headless
        self.block_images = block_images
        self.user_data_dir = user_data_dir
        self.log = logger or Log()
        self.current_bot = None  # 当前运行中的 Bot 实例（信号处理用）

    def _make_bot(self, target_topics):
        """构造一次性的 Bot 实例"""
        cfg = DEFAULT_CONFIG.copy()
        if self.proxy:
            cfg["proxy"] = self.proxy
        cfg["like_rate"] = self.like_rate
        cfg["block_images"] = self.block_images

        return Bot(
            cfg,
            CATS,
            self.log.info,
            mode="topics",
            target_value=target_topics,
            enable_like=True,
            enable_reply=False,  # Docker 版默认不自动回帖（避免被检测）
            enable_wait=True,
            browse_mode="deep",
            headless=self.headless,
            block_images=self.block_images,
            user_data_dir=self.user_data_dir,
        )

    def run_once(self, target_topics=None):
        """执行一次浏览任务"""
        if target_topics is None:
            target_topics = random.randint(*self.topics_range)

        self.log.info("=" * 50)
        self.log.info(f"开始浏览任务 | 目标: {target_topics} 个帖子")
        self.log.info("=" * 50)

        bot = self._make_bot(target_topics)
        self.current_bot = bot
        start = time.time()

        try:
            bot.run_session(username=self.username, password=self.password)
        finally:
            bot.close()
            self.current_bot = None

        elapsed = int(time.time() - start)
        self.log.info("=" * 50)
        self.log.ok(f"任务完成 | 用时 {elapsed // 60}分{elapsed % 60}秒")
        self.log.ok(
            f"浏览 {bot.stats['topic']} | "
            f"点赞 {bot.stats['like'] + bot.stats['like_reply']} | "
            f"爬楼 {bot.stats['floors']}"
        )
        self.log.info("=" * 50)


class RandomScheduler:
    """每天随机生成 N 个运行时间点，模拟真人使用习惯"""

    def __init__(self, bot, runs_per_day=2, topics_range=DEFAULT_TOPICS_RANGE):
        self.bot = bot
        self.runs_per_day = runs_per_day
        self.topics_range = topics_range
        self.today_schedule = []
        self.running = True
        self._ran_today = False  # 今天是否已执行过任务（补跑判断用）

    def _generate_daily_schedule(self):
        """生成今天的随机运行时间

        若生成的有效时间点为 0（启动太晚，如 22:00 后），
        且今天还没跑过任务，则当日再补跑一次（30-90 分钟内随机触发）。
        """
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        times = []

        for _ in range(self.runs_per_day):
            # 在 7:00 - 23:00 之间随机选择时间
            hour = random.randint(*SCHEDULE_HOUR_RANGE)
            minute = random.randint(0, 59)
            run_time = today.replace(hour=hour, minute=minute)
            # 只保留未来的时间
            if run_time > now:
                times.append(run_time)

        times.sort()

        # 傍晚启动且一个未来时间点都没有：当天补跑一次，避免闲一整天
        if not times and not self._ran_today and now.hour < 23:
            catch_up = now + timedelta(minutes=random.randint(30, 90))
            if catch_up.hour < 23:
                times.append(catch_up)
                self.bot.log.info(
                    f"今日计划时间已过，安排补跑: {catch_up.strftime('%H:%M')}"
                )

        self._ran_today = False
        self.today_schedule = times

        self.log_schedule()

        return times

    def log_schedule(self):
        self.bot.log.info(f"今日计划 ({len(self.today_schedule)} 次):")
        for t in self.today_schedule:
            self.bot.log.info(f"  {t.strftime('%H:%M')} - 浏览随机数量的帖子")

    def _run_task(self):
        """执行一次任务（异常隔离：单次失败不影响常驻调度）"""
        topics = random.randint(*self.topics_range)
        self.bot.log.info(f"定时任务触发 | 目标 {topics} 个帖子")
        try:
            self.bot.run_once(target_topics=topics)
        except Exception as e:
            self.bot.log.err(f"任务异常（调度器继续运行）: {e}")

    def start(self):
        """启动调度器"""
        self.bot.log.info("=" * 50)
        self.bot.log.info("Linux.do 自动刷帖调度器启动 (CloakBrowser)")
        self.bot.log.info(f"每天运行 {self.runs_per_day} 次")
        self.bot.log.info(
            f"每次浏览 {self.topics_range[0]}-{self.topics_range[1]} 个帖子"
        )
        self.bot.log.info("=" * 50)

        # 首次启动立即运行一次
        startup_run = os.environ.get("RUN_ON_START", "true").lower() == "true"
        if startup_run:
            self.bot.log.info("首次启动，立即执行一次...")
            self._run_task()

        while self.running:
            # 每天凌晨生成新的计划
            self._generate_daily_schedule()

            # 等待并执行今天的计划
            for run_time in self.today_schedule:
                if not self.running:
                    break

                now = datetime.now()
                if run_time <= now:
                    continue

                wait_seconds = (run_time - now).total_seconds()
                # 添加 ±15 分钟的随机偏移
                jitter = random.randint(-900, 900)
                wait_seconds = max(60, wait_seconds + jitter)

                next_run = now + timedelta(seconds=wait_seconds)
                self.bot.log.info(
                    f"下次运行: {next_run.strftime('%H:%M:%S')} (等待 {int(wait_seconds / 60)} 分钟)"
                )

                # 分段等待，方便中断
                while wait_seconds > 0 and self.running:
                    time.sleep(min(60, wait_seconds))
                    wait_seconds -= 60

                if self.running:
                    self._run_task()
                    self._ran_today = True

            # 今天的计划执行完毕，等到明天
            if self.running:
                now = datetime.now()
                tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0)
                wait = (tomorrow - now).total_seconds()
                self.bot.log.info(f"今日任务完成，等待明天 ({int(wait / 3600)} 小时后)")
                while wait > 0 and self.running:
                    time.sleep(min(300, wait))
                    wait -= 300

    def stop(self):
        self.running = False


# ==================== 命令行入口 ====================


def parse_args(argv=None):
    """解析命令行参数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Linux.do 自动刷帖 Docker 版（随机调度 + CloakBrowser）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py docker -u myuser -p mypass
  python main.py docker -u myuser -p mypass --runs-per-day 2
  python main.py docker -u myuser -p mypass --once

环境变量:
  LINUXDO_USERNAME  用户名
  LINUXDO_PASSWORD  密码
  LINUXDO_PROXY     代理地址（可选）
        """,
    )

    parser.add_argument("-u", "--username", help="用户名")
    parser.add_argument("-p", "--password", help="密码")
    parser.add_argument(
        "--like-rate", type=int, default=None, help="点赞概率 0-100（默认 30，或环境变量 LIKE_RATE）"
    )
    parser.add_argument(
        "--runs-per-day", type=int, default=None, help="每天运行次数（默认 2，或环境变量 RUNS_PER_DAY）"
    )
    parser.add_argument(
        "--topics-min", type=int, default=None, help="每次最少浏览帖子数（默认 15，或环境变量 TOPICS_MIN）"
    )
    parser.add_argument(
        "--topics-max", type=int, default=None, help="每次最多浏览帖子数（默认 40，或环境变量 TOPICS_MAX）"
    )
    parser.add_argument(
        "--proxy", help="代理地址，如 127.0.0.1:7897（或环境变量 LINUXDO_PROXY）"
    )
    parser.add_argument(
        "--no-headless", action="store_true", help="禁用无头模式（显示浏览器窗口）"
    )
    parser.add_argument(
        "--load-images",
        action="store_true",
        help="加载图片（默认禁用图片以降低流量和首屏时间，弱网推荐）",
    )
    parser.add_argument(
        "--user-data-dir", help="用户数据目录（或环境变量 CHROME_USER_DATA）"
    )
    parser.add_argument("--once", action="store_true", help="只运行一次，不启动调度器")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    return parser.parse_args(argv)


def main(argv=None):
    """主函数"""
    args = parse_args(argv)

    logger = Log(debug=args.debug)

    username = args.username or os.environ.get("LINUXDO_USERNAME")
    password = args.password or os.environ.get("LINUXDO_PASSWORD")

    if not username or not password:
        print("错误: 请提供用户名和密码")
        print("  环境变量: LINUXDO_USERNAME / LINUXDO_PASSWORD")
        print("  命令行:   -u 用户名 -p 密码")
        sys.exit(1)

    proxy = args.proxy or os.environ.get("LINUXDO_PROXY")

    # 参数优先级：命令行 > 环境变量 > 默认值
    def _pick(arg_val, env_key, default):
        if arg_val is not None:
            return arg_val
        env = os.environ.get(env_key)
        if env:
            return env
        return default

    try:
        like_rate = int(_pick(args.like_rate, "LIKE_RATE", 30))
        runs_per_day = int(_pick(args.runs_per_day, "RUNS_PER_DAY", 2))
        topics_min = int(_pick(args.topics_min, "TOPICS_MIN", 15))
        topics_max = int(_pick(args.topics_max, "TOPICS_MAX", 40))
    except ValueError as e:
        logger.err(f"参数解析失败: {e}")
        sys.exit(1)

    topics_range = (max(1, topics_min), max(topics_min + 1, topics_max))

    bot = DockerBot(
        username=username,
        password=password,
        like_rate=like_rate / 100,
        topics_range=topics_range,
        proxy=proxy,
        headless=not args.no_headless,
        block_images=not args.load_images,
        user_data_dir=args.user_data_dir or os.environ.get("CHROME_USER_DATA"),
        logger=logger,
    )

    logger.info(f"Linux.do 自动刷帖 Docker 版启动 (v{__version__}, CloakBrowser)")

    if args.once:
        topics = random.randint(*topics_range)
        bot.run_once(target_topics=topics)
    else:
        scheduler = RandomScheduler(
            bot,
            runs_per_day=runs_per_day,
            topics_range=topics_range,
        )

        def handle_signal(sig, frame):
            logger.info("收到停止信号，正在退出...")
            scheduler.stop()
            # 同时停掉正在运行的任务，避免 Ctrl+C 后浏览器继续跑完整个任务
            if bot.current_bot is not None:
                try:
                    bot.current_bot.stop()
                except Exception:
                    pass

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        scheduler.start()


if __name__ == "__main__":
    main()
