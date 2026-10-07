# -*- coding: utf-8 -*-
"""把 Clash 订阅内容准备好，供粘贴/上传到 GitHub Secret CLASH_SUB_CONTENT。

背景：
    1. 很多机场把订阅接口放在 Cloudflare 后面并拦截数据中心 IP，
       GitHub Actions 上拉订阅会 403——把订阅「文件内容」直接进 Secret 可绕开
    2. 完整订阅文件常超过 GitHub Secret 的 48KB 上限，而 mihomo 只需要
       「proxies: 节点列表」——本脚本自动只提取节点部分（通常 <25KB）

用法（二选一）：
    python prepare_sub_secret.py <订阅链接>
    python prepare_sub_secret.py <本地yaml>   # 如 Clash Verge 的 profile 文件

    Verge 配置目录：C:\\Users\\<用户>\\AppData\\Roaming\\io.github.clash-verge-rev.clash-verge-rev\\profiles\\
    选最新最大的 .yaml（右键订阅 -> 打开文件 可定位）

结果存到 sub_secret_content.txt（已 gitignore），Windows 下自动复制到剪贴板。
然后用下面任一方式上传 Secret：
    gh secret set CLASH_SUB_CONTENT < sub_secret_content.txt
    或 GitHub 网页 -> Settings -> Secrets -> 手动粘贴

注意：sub_secret_content.txt 含节点凭据，用完删除，别提交进仓库。
"""

import base64
import re
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK，避免输出 ✓ 等字符时崩
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT_FILE = Path(__file__).parent / "sub_secret_content.txt"
# GitHub Secret 硬上限 48KB（48 * 1024 字节），留裕量
MAX_SECRET_BYTES = 46 * 1024


def extract_proxies_yaml(text: str) -> str | None:
    """从 Clash YAML 里只提取顶层 proxies: 列表，返回最小 YAML 文本。

    mihomo 的 proxy-provider 只需要 proxies: 字段；dns/rules/proxy-groups
    全部丢弃，把体积压到 Secret 上限以内。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    in_proxies = False
    for line in lines:
        if re.match(r"^proxies:\s*$", line):
            in_proxies = True
            out.append(line)
            continue
        if in_proxies:
            # 顶层新键（无缩进且非空非注释）= proxies 列表结束
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            if line.strip():
                out.append(line)
    if not out:
        return None
    return "\n".join(out) + "\n"


def looks_like_clash_yaml(text: str) -> bool:
    return "proxies:" in text


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
            capture_output=True, text=True, encoding="utf-8", errors="replace",
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

    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")

    if looks_like_clash_yaml(content):
        print("检测到 Clash YAML 订阅，提取 proxies: 节点列表...")
        trimmed = extract_proxies_yaml(content)
        if not trimmed:
            print("错误: YAML 里没有找到 proxies: 节点列表")
            sys.exit(1)
        content = trimmed
    else:
        # 尝试 base64（v2ray 通用格式）
        try:
            compact = "".join(content.split())
            decoded = base64.b64decode(
                compact.replace("-", "+").replace("_", "/")
                + "=" * (-len(compact) % 4),
                validate=True,
            ).decode("utf-8")
            if "proxies:" in decoded:
                print("检测到 base64 订阅，已解码并提取节点列表")
                content = extract_proxies_yaml(decoded) or decoded
            elif any(x in decoded for x in ("vmess://", "vless://", "trojan://", "ss://")):
                print("错误: 这是 v2ray 节点链接格式（vmess:// 等），不是 Clash 订阅。")
                print("      请在 Clash Verge 里导入后再取它的 profile .yaml 文件")
                sys.exit(1)
            else:
                print("错误: 内容既不是 Clash YAML 也不是已知订阅格式")
                sys.exit(1)
        except Exception:
            print("错误: 内容既不是 Clash YAML 也不是 base64 订阅")
            sys.exit(1)

    size = len(content.encode("utf-8"))
    if size > MAX_SECRET_BYTES:
        print(f"错误: 提取后仍有 {size} 字节，超过 Secret 上限 {MAX_SECRET_BYTES} 字节")
        print("      （节点太多时可能出现；可手动删掉不用的地区节点后重跑）")
        sys.exit(1)

    OUT_FILE.write_text(content, encoding="utf-8")
    n_nodes = len(re.findall(r"^\s*-\s*\{?\s*name:", content, re.M))
    print(f"\n已保存: {OUT_FILE}")
    print(f"  节点数: {n_nodes}，体积: {size} 字节（Secret 上限 {MAX_SECRET_BYTES} 内 ✓）")

    # Windows 复制到剪贴板
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["clip"], input=content.encode("utf-16-le").decode("utf-8"),
                capture_output=True, check=True,
            )
            print("已复制到剪贴板 ✓")
        except Exception:
            print("剪贴板复制失败，请手动打开文件复制")

    print("\n上传 Secret（二选一）:")
    print(f"  gh secret set CLASH_SUB_CONTENT < {OUT_FILE.name}")
    print("  或 GitHub 网页 -> Settings -> Secrets -> New repository secret")
    print(f"\n提醒: {OUT_FILE.name} 含节点凭据，用完删除，勿提交仓库")


if __name__ == "__main__":
    main()
