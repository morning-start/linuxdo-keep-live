# -*- coding: utf-8 -*-
"""模块自测：调度器纯逻辑 + 参数解析 + profile 锁清理（不启动浏览器）。"""
from datetime import datetime

from linuxdo_keep_live import docker as dk
from linuxdo_keep_live.bot import Bot
from linuxdo_keep_live.docker import Log, RandomScheduler, parse_args

# 1. 默认参数
a = parse_args(["-u", "u", "-p", "p"])
assert a.username == "u" and a.password == "p"
assert a.runs_per_day == 2 and a.topics_min == 15 and a.topics_max == 40
assert a.like_rate == 30 and not a.once
print("[1] docker parse_args 默认值 OK")

a2 = parse_args(["-u", "u", "-p", "p", "--runs-per-day", "3", "--topics-min", "10",
                 "--topics-max", "25", "--once", "--no-headless", "--debug"])
assert a2.runs_per_day == 3 and a2.topics_min == 10 and a2.topics_max == 25
assert a2.once and a2.no_headless and a2.debug
print("[2] docker parse_args 自定义值 OK")

# 3. 缺账号密码时退出码为 1（在 main() 内部分支验证）
class _FakeBot:
    def __init__(self):
        self.log = Log(debug=False)
        self.calls = []

    def run_once(self, target_topics=None):
        self.calls.append(target_topics)

fake = _FakeBot()
sched = RandomScheduler(fake, runs_per_day=2, topics_range=(15, 40))

# 4. 今日计划生成：时间点数量 <= runs_per_day，且都在今天
now = datetime.now()
times = sched._generate_daily_schedule()
assert len(times) <= 2
for t in times:
    assert t.date() == now.date()
    assert 7 <= t.hour <= 23
assert times == sorted(times)
print(f"[3] RandomScheduler 今日计划 OK ({len(times)} 个时间点)")

# 5. 任务执行走 bot.run_once，且帖子数落在范围内
sched._run_task()
assert len(fake.calls) == 1
assert 15 <= fake.calls[0] <= 40
print("[4] RandomScheduler._run_task OK, target =", fake.calls[0])

# 6. 停止标志
sched.stop()
assert sched.running is False
print("[5] RandomScheduler.stop OK")

# 7. DockerBot._make_bot 构造（不启动浏览器）
db = dk.DockerBot("u", "p", like_rate=0.3, topics_range=(15, 40), proxy="127.0.0.1:7897")
bot = db._make_bot(20)
assert bot.mode == "topics" and bot.target_value == 20
assert bot.enable_like and not bot.enable_reply and bot.headless
assert bot.cfg["like_rate"] == 0.3 and bot.cfg["proxy"] == "127.0.0.1:7897"
assert bot.user_data_dir.endswith("browser_data")
print("[6] DockerBot._make_bot OK")

# 7. Singleton 锁清理
import os
import tempfile

tmp = tempfile.mkdtemp(prefix="lk_lock_test_")
for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
    open(os.path.join(tmp, name), "w").close()
open(os.path.join(tmp, "Preferences"), "w").close()  # 非锁文件应保留
removed = Bot._clear_profile_locks(tmp)
assert set(removed) == {"SingletonLock", "SingletonSocket", "SingletonCookie"}, removed
assert os.path.exists(os.path.join(tmp, "Preferences")), "非锁文件不应被删除"
os.remove(os.path.join(tmp, "Preferences"))
os.rmdir(tmp)
print("[7] _clear_profile_locks OK")

print("MODULE TESTS PASSED")
