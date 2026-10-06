# -*- coding: utf-8 -*-
"""把 Clash 订阅内容准备好，供粘贴到 GitHub Secret CLASH_SUB_CONTENT。

背景：
    很多机场把订阅接口放在 Cloudflare 后面并拦截数据中心 IP，
    GitHub Actions 上拉订阅会 403。把订阅「文件内容」直接贴进 Secret
    可彻底绕开（workflow 会检测到 CLASH_SUB_CONTENT 优先使用）。

用法：
    python prepare_sub_secret.py <订阅链接或本地yaml路径>

    - 传 https:// 链接：用系统 curl 拉取（走你本机网络，家宽 IP 不被拦）
    - 传本地 .yaml 路径：直接读取（如 Clash Verge 配置目录里的订阅文件）
    结果存到 sub_secret_content.txt，同时复制到剪贴板（Windows），
    去 GitHub -> Settings -> Secrets -> New repository secret，
    名字填 CLASH_SUB_CONTENT，内容整段粘贴即可。

注意：sub_secret_content.txt 含节点凭据，用完记得删除，别提交进仓库。
"""

import base64
import subprocess
import sys
from pathlib import Path

OUT_FILE = Path(__file__).parent / "sub_secret_content.txt"


def looks_like_clash_yaml(text: str) -> bool:
    return "proxies:" in text and ("proxy-groups:" in text or "proxy-providers:" in text)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src = sys.argv[1]
    if src.startswith("http://") or src.startswith("https://"):
        print(f"从网络拉取订阅（走本机网络）: {src[:60]}...")
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "30",
             "-A", "clash-verge/v1.7.7", src],
            capture_output=True, text=True, encoding="utf-8",
        )
        content = r.stdout
        if not content:
            print(f"拉取失败: {r.stderr[:200]}")
            sys.exit(1)
    else:
        p = Path(src)
        if not p.exists():
            print(f"文件不存在: {p}")
            sys.exit(1)
        content = p.read_text(encoding="utf-8", errors="replace")

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = content.lstrip("\ufeff")

    if looks_like_clash_yaml(content):
        print("检测到 Clash YAML 订阅 ✓")
    else:
        # 尝试 base64（v2ray 通用格式）
        try:
            decoded = base64.b64decode(
                "".join(content.split()).replace("-", "+").replace("_", "/")
                + "=" * (-len("".join(content.split())) % 4),
                validate=True,
            ).decode("utf-8")
            if "proxies:" in decoded:
                content = decoded
                print("检测到 base64 订阅，已解码为 Clash YAML ✓")
            else:
                print("⚠ 内容不含 proxies: 字段，可能不是完整订阅文件")
        except Exception:
            print("⚠ 内容不含 proxies: 字段，可能不是完整订阅文件")

    OUT_FILE.write_text(content, encoding="utf-8")
    print(f"\n已保存: {OUT_FILE}（{len(content)} 字符）")

    # Windows 复制到剪贴板
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["clip"], input=content.encode("utf-16-le").decode("utf-8"),
                capture_output=True, check=True,
            )
            print("已复制到剪贴板 ✓  直接去 GitHub Secret 粘贴即可")
        except Exception:
            print("剪贴板复制失败，请手动打开文件复制")

    print("\n下一步：GitHub 仓库 -> Settings -> Secrets and variables -> Actions")
    print("  -> New repository secret -> Name: CLASH_SUB_CONTENT")
    print("  -> Secret: 整段粘贴 -> Add secret")
    print(f"\n提醒：{OUT_FILE.name} 含节点凭据，用完删除，勿提交仓库（已加入 .gitignore）")


if __name__ == "__main__":
    main()
