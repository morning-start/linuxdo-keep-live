# -*- coding: utf-8 -*-
"""登录状态诊断：检测程序自带的浏览器 profile 是否已登录 linux.do。

常见困惑：「我明明已经登录了，为什么还提示未检测到登录？」
—— 程序使用自己独立的浏览器 profile（browser_data/），
   与您日常使用的浏览器相互独立，需要在程序弹出的浏览器窗口里登录一次。

本脚本会告诉您：
    1. 会话 API 是否判定已登录（/session/current.json）
    2. DOM 标记 #current-user 是否存在
    3. 综合检测结果与检测途径
    4. 当前页面现场（标题/Cloudflare 挑战/登录链接）

用法：
    python login_check.py
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


def main():
    cfg = DEFAULT_CONFIG.copy()

    logs = []
    bot = Bot(cfg, CATS, logs.append, mode="endless", headless=True, humanize=True)
    print("启动浏览器（直连，不使用代理）...")
    if not bot.start():
        for line in logs:
            print("LOG |", line)
        sys.exit("浏览器启动失败，原因见上方日志")

    pg = bot.pg
    if not bot._goto_with_hint(cfg["base"], "首页"):
        bot.close()
        sys.exit("无法打开 linux.do 首页（网络或代理问题），可运行 python proxy_check.py 排查")
    time.sleep(5)

    print("\n== 1) 会话 API (/session/current.json) ==")
    logged_in, username = bot._api_check_login()
    print(f"   logged_in={logged_in}  username={username}")

    print("== 2) DOM 标记 #current-user ==")
    print("   存在:", bot._has("#current-user", timeout_ms=3000))

    print("== 3) 综合检测 _detect_login ==")
    result = bot._detect_login()
    print(
        f"   found={result['found']}  via={result['via']}  username={result.get('username')}"
    )

    print("== 4) 页面现场 ==")
    for k, v in bot._page_diag().items():
        print(f"   {k}: {v!r}")

    print("\n== 5) check_login 实际调用 ==")
    bot.run = True
    ok = bot.check_login(wait_for_login=False, max_wait=10, check_interval=2)
    print("   结果:", ok)

    bot.close()

    if ok:
        print("\n结论: profile 已登录 ✅ 程序应能正常检测到")
        sys.exit(0)

    print("\n结论: 未检测到登录 ❌")
    print("可能原因：")
    print("  1. 还没在【本程序弹出的浏览器窗口】里登录（日常浏览器登录不算）")
    print("  2. 页面被 Cloudflare 人机验证挡住（见上方页面现场 cf 字段）")
    print("  3. 登录态过期/被登出，重新在程序窗口登录一次")
    print("  4. 代理设置问题，可运行 python proxy_check.py 排查")
    sys.exit(1)


if __name__ == "__main__":
    main()
