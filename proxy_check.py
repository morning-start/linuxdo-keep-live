# -*- coding: utf-8 -*-
"""代理连通性诊断：验证当前代理设置下浏览器能否打开 linux.do。

用途：
    - 排查 ERR_PROXY_CONNECTION_FAILED 一类错误
    - 对比「有代理 / 无代理」两种配置的差异

用法：
    python proxy_check.py                # 按默认配置测试（默认直连）
    python proxy_check.py 127.0.0.1:7897 # 测试指定代理端口

结果说明：
    - TUN 模式（虚拟网卡）/ 系统代理：留空即可，应选择直连
    - 代理软件 mixed 端口：填入 http://127.0.0.1:7897 等地址
"""

import sys

from linuxdo_keep_live.bot import Bot, is_proxy_error
from linuxdo_keep_live.config import CATS, DEFAULT_CONFIG

# Windows 控制台默认 GBK 编码，无法输出 ⚠/✅ 等 emoji，切换到 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def check(proxy: str) -> bool:
    cfg = DEFAULT_CONFIG.copy()
    cfg["proxy"] = proxy

    logs = []
    bot = Bot(cfg, CATS, logs.append, mode="endless", headless=True, humanize=True)
    print(f"\n=== 测试代理配置: {proxy or '(空，直连)'} ===")

    if not bot.start():
        return False

    ok = bot._goto_with_hint(cfg["base"], "首页")
    for line in logs:
        print("LOG |", line)
    bot.close()
    return ok


def main():
    proxy = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG["proxy"]

    print("默认代理配置:", repr(DEFAULT_CONFIG["proxy"]) or "(空)")

    ok = check(proxy)
    if ok:
        print("\n结论: 代理配置可用 ✅")
        sys.exit(0)

    print("\n结论: 无法打开首页 ❌")
    if proxy:
        print("建议: 若你使用 TUN 模式（虚拟网卡）或系统代理，请留空代理直连；")
        print("      若必须使用代理，请检查代理软件是否运行、端口是否正确。")
    else:
        print("建议: 直连失败，请检查网络，或填写代理地址后重试。")
    sys.exit(1)


if __name__ == "__main__":
    main()
