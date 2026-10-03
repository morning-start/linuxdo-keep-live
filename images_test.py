# -*- coding: utf-8 -*-
"""图片禁用效果测试：弱网限速下对比 禁用图片 vs 加载图片。

用例直接走生产路径 Bot.get_topics()，验证：
    1. 禁用图片后图片请求确实被拦截
    2. 帖子列表仍能正常加载（不误伤功能）
    3. 耗时对比（沙箱网络波动大，仅作参考）
"""
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


def run_case(block_images: bool):
    """跑一次真实 get_topics 流程，返回 (话题数, 耗时, 被拦图片数)"""
    cfg = DEFAULT_CONFIG.copy()
    cfg["proxy"] = ""
    cfg["block_images"] = block_images

    blocked = {"images": 0}
    logs = []
    bot = Bot(
        cfg, CATS, logs.append, mode="endless", headless=True, humanize=True,
        block_images=block_images,
    )
    if not bot.start():
        raise SystemExit(f"浏览器启动失败: " + "\n".join(logs))

    def on_request_failed(req):
        try:
            if req.resource_type == "image":
                blocked["images"] += 1
        except Exception:
            pass

    bot.pg.on("requestfailed", on_request_failed)

    # CDP 弱网：200KB/s + 400ms，禁用缓存保证两次用例都真实走网络
    try:
        cdp = bot.ctx.new_cdp_session(bot.pg)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "downloadThroughput": 200 * 1024,
                "uploadThroughput": 200 * 1024,
                "latency": 400,
            },
        )
    except Exception as e:
        print(f"CDP 限速失败: {e}")

    t0 = time.time()
    topics = bot.get_topics(CATS[0])  # 生产路径：domcontentloaded + 等列表渲染
    elapsed = time.time() - t0
    time.sleep(1)  # 让 failed 事件回调落地

    bot.close()
    time.sleep(2)  # 等 profile 锁释放
    return len(topics), elapsed, blocked["images"]


def main():
    print("== 用例 A: 禁用图片（默认）==")
    a_topics, a_time, a_blocked = run_case(block_images=True)
    print(f"   话题数: {a_topics} | 耗时: {a_time:.1f}s | 被拦图片请求: {a_blocked}")

    print("== 用例 B: 加载图片 ==")
    b_topics, b_time, b_blocked = run_case(block_images=False)
    print(f"   话题数: {b_topics} | 耗时: {b_time:.1f}s | 被拦图片请求: {b_blocked}")

    # 功能断言（必须成立）
    assert a_topics > 0, "禁用图片后仍应取到话题"
    assert a_blocked > 0, "禁用图片应有图片请求被拦截"
    assert b_blocked == 0, "加载图片时不应拦截"
    assert b_topics > 0, "加载图片时应取到话题"

    print(f"\n耗时对比: 禁用图片 {a_time:.1f}s vs 加载图片 {b_time:.1f}s")
    print(f"节省图片请求: {a_blocked} 个（弱网下直接减少流量与首屏时间）")
    print("IMAGE BLOCK TEST PASSED ✅（功能断言全部通过）")


if __name__ == "__main__":
    main()
