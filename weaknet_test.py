# -*- coding: utf-8 -*-
"""弱网复现测试：限速下验证 get_topics 会等列表渲染完再取数。"""
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from linuxdo_keep_live.bot import Bot
from linuxdo_keep_live.config import CATS, DEFAULT_CONFIG

cfg = DEFAULT_CONFIG.copy()
cfg["proxy"] = ""

logs = []
bot = Bot(cfg, CATS, logs.append, mode="endless", headless=True, humanize=True)
if not bot.start():
    for line in logs:
        print("LOG |", line)
    raise SystemExit("浏览器启动失败")

# 通过 CDP 模拟弱网：上下行 200KB/s、延迟 400ms
try:
    cdp = bot.ctx.new_cdp_session(bot.pg)
    cdp.send("Network.enable")
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "downloadThroughput": 200 * 1024,
            "uploadThroughput": 200 * 1024,
            "latency": 400,
        },
    )
    print("已启用弱网模拟: 200KB/s + 400ms 延迟")
except Exception as e:
    print(f"CDP 限速失败（不影响主流程）: {e}")

# 记录旧行为作为对照：goto 后立即取数
bot.pg.goto(cfg["base"] + CATS[0]["u"])
immediate = bot.pg.evaluate(
    "() => document.querySelectorAll('tr.topic-list-item').length"
)
print(f"goto 返回瞬间的行数（旧逻辑此时就会取数）: {immediate}")

# 新逻辑：get_topics（内部会等待列表渲染 + 一次刷新重试）
t0 = time.time()
topics = bot.get_topics(CATS[0])
elapsed = time.time() - t0
print(f"get_topics 结果: {len(topics)} 个话题（耗时 {elapsed:.1f}s）")
if topics:
    print("示例:", topics[0]["title"][:30], "| unread =", topics[0]["isUnread"])

bot.close()

assert len(topics) > 0, f"弱网下仍应取到话题，实际 {len(topics)}"
print("\nWEAK NETWORK TEST PASSED ✅")
