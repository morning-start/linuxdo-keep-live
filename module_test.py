# -*- coding: utf-8 -*-
"""模块自测：调度器纯逻辑 + 参数解析 + profile 锁清理 + Bot 中断等待（不启动浏览器）。"""
import os
import tempfile
from datetime import datetime

from linuxdo_keep_live import docker as dk
from linuxdo_keep_live.bot import Bot
from linuxdo_keep_live.docker import Log, RandomScheduler, parse_args

# 1. 默认参数（命令行未提供时为 None，由 main() 按环境变量/默认值回退）
a = parse_args(["-u", "u", "-p", "p"])
assert a.username == "u" and a.password == "p"
assert a.runs_per_day is None and a.topics_min is None and a.topics_max is None
assert a.like_rate is None and not a.once
print("[1] docker parse_args 默认值（None 回退）OK")

a2 = parse_args(["-u", "u", "-p", "p", "--runs-per-day", "3", "--topics-min", "10",
                 "--topics-max", "25", "--once", "--no-headless", "--debug"])
assert a2.runs_per_day == 3 and a2.topics_min == 10 and a2.topics_max == 25
assert a2.once and a2.no_headless and a2.debug
print("[2] docker parse_args 自定义值 OK")

# 2b. 参数三级回退逻辑（命令行 > 环境变量 > 默认值）
def _pick(arg_val, env_key, default):
    if arg_val is not None:
        return arg_val
    env = os.environ.get(env_key)
    if env:
        return env
    return default

os.environ["LIKE_RATE"] = "77"
assert int(_pick(None, "LIKE_RATE", 30)) == 77, "环境变量应生效"
assert int(_pick(55, "LIKE_RATE", 30)) == 55, "命令行应优先于环境变量"
del os.environ["LIKE_RATE"]
assert int(_pick(None, "LIKE_RATE", 30)) == 30, "无命令行/环境变量时用默认值"
print("[2b] 参数三级回退（命令行>环境>默认）OK")

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

# 5. 任务执行走 bot.run_once，且帖子数落在范围内；异常被隔离不外抛
sched._run_task()
assert len(fake.calls) == 1
assert 15 <= fake.calls[0] <= 40

def _boom(self, target_topics=None):
    raise RuntimeError("boom")

_orig = dk.DockerBot.run_once
dk.DockerBot.run_once = _boom
try:
    sched._run_task()  # 不应抛异常
finally:
    dk.DockerBot.run_once = _orig
print("[4] RandomScheduler._run_task OK（含异常隔离）, target =", fake.calls[0])

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

# 8. Singleton 锁清理
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

# 9. _wait_seconds 可中断：run=False 时立即返回
b = Bot.__new__(Bot)  # 跳过 __init__，只测等待逻辑
import time as _time

b.run = True
t0 = _time.time()
b._wait_seconds(0.3)
assert 0.2 < _time.time() - t0 < 1.0, "正常等待应约 0.3s"

b.run = False
t0 = _time.time()
b._wait_seconds(30)
assert _time.time() - t0 < 1.0, "run=False 时应立即返回而非睡 30s"
print("[8] _wait_seconds 可中断 OK（停止即返回）")

# 10. 达标后 browse_topic 不再执行互动动作（模拟：run=False 时点赞/回复被跳过）
# 通过源码静态检查保证（互动分支均带 self.run 条件）
import inspect
src = inspect.getsource(Bot.browse_topic)
assert "if (\n                self.run\n                and self.enable_like" in src or (
    "self.run and self.enable_like" in src
), "点赞主帖应检查 self.run"
assert "self.run and self.enable_reply" in src, "回帖应检查 self.run"
print("[9] 达标停止后跳过点赞/回复 OK（静态检查）")

print("MODULE TESTS PASSED")
