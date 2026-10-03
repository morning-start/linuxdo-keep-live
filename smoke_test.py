# -*- coding: utf-8 -*-
"""冒烟测试：验证 CloakBrowser 集成可用。

运行：
    python smoke_test.py

说明：
    - 不登录，仅验证浏览器启动 / 页面导航 / JS 执行 / 元素定位
    - 在本机可正常访问 linux.do 时，会顺带抓取一次板块帖子列表
"""

import time

from linuxdo_keep_live.bot import Bot, normalize_proxy
from linuxdo_keep_live.config import CATS, DEFAULT_CONFIG


def main():
    # 1. 代理地址归一化
    assert normalize_proxy("127.0.0.1:7897") == "http://127.0.0.1:7897"
    assert normalize_proxy("http://127.0.0.1:7897") == "http://127.0.0.1:7897"
    assert normalize_proxy("socks5://user:pass@1.2.3.4:1080") == "socks5://user:pass@1.2.3.4:1080"
    assert normalize_proxy("") is None
    assert normalize_proxy(None) is None
    print("[1] normalize_proxy OK")

    cfg = DEFAULT_CONFIG.copy()
    cfg["proxy"] = ""  # 冒烟测试不走代理

    logs = []
    bot = Bot(cfg, CATS, logs.append, mode="endless", headless=True, humanize=True)
    assert bot.start(), "浏览器启动失败"
    print("[2] CloakBrowser 启动 OK")

    bot.pg.goto("https://example.com")
    time.sleep(2)
    print("[3] goto example.com OK, title =", bot.pg.title())
    assert bot.pg.evaluate("() => 1 + 1") == 2
    print("    evaluate OK")

    # 4. 访问 linux.do 首页 + 板块页（本机网络可达时有效）
    try:
        bot.pg.goto(cfg["base"])
        time.sleep(4)
        print("[4] goto linux.do OK, title =", bot.pg.title())
        print("    has #current-user (未登录应为 False):", bot._has("#current-user", 3000))
        topics = bot.get_topics(CATS[0])
        print(f"    get_topics({CATS[0]['n']}) -> {len(topics)} 个话题")
    except Exception as e:
        print(f"[4] linux.do 访问失败（可能是网络/Cloudflare 限制）: {e}")

    bot.close()
    print("[5] 浏览器关闭 OK")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
