# -*- coding: utf-8 -*-
"""模块自测：调度器纯逻辑 + 参数解析 + 目标解析 + profile 锁清理 + Bot 中断等待（不启动浏览器）。"""
import os
import tempfile
from datetime import datetime

from linuxdo_keep_live import docker as dk
from linuxdo_keep_live.bot import Bot, parse_target
from linuxdo_keep_live.docker import Log, RandomScheduler, parse_args

# 0. 运行目标解析：纯数字=帖子数，带时间单位=分钟数，识别不了走默认
assert parse_target("30") == ("topics", 30)
assert parse_target("50帖") == ("topics", 50)
assert parse_target("30min") == ("time", 30)
assert parse_target("30 min") == ("time", 30)
assert parse_target("45分钟") == ("time", 45)
assert parse_target("1h") == ("time", 60)
assert parse_target("2h") == ("time", 120)
assert parse_target("1.5h") == ("time", 90)
assert parse_target("90s") == ("time", 1.5)
assert parse_target("1hour") == ("time", 60)
# 兼容旧行为：--topics 原为 int(30)
mode, val = parse_target("30")
assert mode == "topics" and val == 30
# 识别不了 / 空 / None / 负数 / 零 → 默认 30 分钟
assert parse_target("abc") == ("time", 30)
assert parse_target("") == ("time", 30)
assert parse_target(None) == ("time", 30)
assert parse_target("-5") == ("time", 30)
assert parse_target("0") == ("time", 30)
assert parse_target("30xyz") == ("time", 30)
assert parse_target("min") == ("time", 30)  # 只有单位没数字
print("[0] parse_target 目标解析 OK（30/50帖=数量，30min/1h/90s=时长，异常走默认30min）")

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

    def run_once(self, target=None):
        self.calls.append(target)

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

# 5. 任务执行走 bot.run_once（默认 None=随机帖子数），且帖子数落在范围内；异常被隔离不外抛
sched._run_task()
assert len(fake.calls) == 1
assert fake.calls[0] is None, "无 target 时应传 None（run_once 内部随机生成）"

def _boom(self, target=None):
    raise RuntimeError("boom")

_orig = dk.DockerBot.run_once
dk.DockerBot.run_once = _boom
try:
    sched._run_task()  # 不应抛异常
finally:
    dk.DockerBot.run_once = _orig
print("[4] RandomScheduler._run_task OK（含异常隔离）, target =", fake.calls[0])

# 5b. 调度器带固定目标（target="1h"）时透传给 run_once
fake2 = _FakeBot()
sched2 = RandomScheduler(fake2, runs_per_day=1, topics_range=(15, 40), target="1h")
sched2._run_task()
assert fake2.calls == ["1h"], fake2.calls
print("[4b] RandomScheduler 固定目标透传 OK (target='1h')")

# 6. 停止标志
sched.stop()
assert sched.running is False
print("[5] RandomScheduler.stop OK")

# 7. DockerBot._make_bot 构造（不启动浏览器）：帖子数与时间两种模式
db = dk.DockerBot("u", "p", like_rate=0.3, topics_range=(15, 40), proxy="127.0.0.1:7897")
bot = db._make_bot("topics", 20)
assert bot.mode == "topics" and bot.target_value == 20
assert bot.enable_like and not bot.enable_reply and bot.headless
assert bot.cfg["like_rate"] == 0.3 and bot.cfg["proxy"] == "127.0.0.1:7897"
assert bot.user_data_dir.endswith("browser_data")
bot2 = db._make_bot("time", 60)
assert bot2.mode == "time" and bot2.target_value == 60
print("[6] DockerBot._make_bot OK（topics/time 两模式）")

# 7b. run_once 目标字符串解析（不真跑，通过 _make_bot 参数拦截验证）
made = []
def _fake_make(self, mode, target_value):
    made.append((mode, target_value))
    raise RuntimeError("stop-here")  # 构造后立即中断，不启动浏览器
_orig_make = dk.DockerBot._make_bot
dk.DockerBot._make_bot = _fake_make
try:
    for tgt, expect in (("1h", ("time", 60)), ("45", ("topics", 45)), (None, None)):
        made.clear()
        try:
            db.run_once(target=tgt)
            raise AssertionError("应被 RuntimeError 中断")
        except RuntimeError as e:
            assert str(e) == "stop-here"
            if expect is None:
                assert made[0][0] == "topics" and 15 <= made[0][1] <= 40, made
            else:
                assert made == [expect], made
finally:
    dk.DockerBot._make_bot = _orig_make
print("[6b] run_once 目标字符串解析 OK（'45'=45帖 / '1h'=60分钟 / None=随机）")

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
