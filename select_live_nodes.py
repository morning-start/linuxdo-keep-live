# -*- coding: utf-8 -*-
"""从超大订阅里挑出「当前可用」的节点，生成能塞进 GitHub Secret 的精简内容。

场景：订阅有上千个节点（几百 KB），远超 GitHub Secret 48KB 上限；且大量是死节点。
做法：本机启动 mihomo 加载全量节点 -> 用控制 API 并发测活 -> 只保留能连通
      的节点并按延迟排序 -> 裁到 48KB 以内写入 sub_secret_content.txt。
本地测出的活节点，其出口 IP 在 CI 上同样能访问 linux.do（节点 egress 与客户端无关）。

用法：
    python select_live_nodes.py <订阅链接或本地yaml>
    python select_live_nodes.py <url> --workdir node-probe --top 120

产物：sub_secret_content.txt（只含活节点，已裁到上限内），上传：
    gh secret set CLASH_SUB_CONTENT < sub_secret_content.txt
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clash_proxy import ensure_mihomo  # 复用内核下载/解压逻辑

API = "http://127.0.0.1:9090"
# GitHub Secret 上限 48KB，留裕量给 proxies 头与缩进
MAX_SECRET_BYTES = 46 * 1024
# 测活目标：通用连通性端点（能到它就等于能到 linux.do 的 CF）
DELAY_URL = "https://www.gstatic.com/generate_204"
# 经本地 mihomo mixed 端口 7897 实拨
PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})
)


def log(m):
    print(m, flush=True)


def fetch_text(src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        log(f"拉取订阅: {src[:60]}...")
        req = urllib.request.Request(src, headers={"User-Agent": "clash-verge/v1.7.7"})
        t = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    else:
        t = open(src, encoding="utf-8", errors="replace").read()
    return t.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def parse_node_blocks(text: str):
    """把 proxies: 段解析成 [(name, block_text)]，保留原始 YAML 缩进。"""
    lines = text.split("\n")
    # 定位 proxies: 段边界
    start = next((i for i, l in enumerate(lines) if re.match(r"^proxies:\s*$", l)), None)
    if start is None:
        raise SystemExit("订阅里没有 proxies: 段")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] and not lines[j][0].isspace():
            end = j
            break
    blocks, cur, cur_name = [], [], None
    for l in lines[start + 1 : end]:
        m = re.match(r"^(\s*)-\s+name:\s*['\"]?([^'\"]+?)['\"]?\s*$", l)
        if m:
            if cur and cur_name:
                blocks.append((cur_name, "\n".join(cur)))
            cur, cur_name = [l], m.group(2)
        elif cur is not None:
            cur.append(l)
    if cur and cur_name:
        blocks.append((cur_name, "\n".join(cur)))
    return blocks


def write_full_provider(blocks, workdir):
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, "sub-content.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("proxies:\n")
        for _, blk in blocks:
            f.write(blk + "\n")
    return path


def write_config(workdir):
    cfg = (
        "mixed-port: 7897\nallow-lan: false\nmode: rule\nlog-level: warning\n"
        "external-controller: 127.0.0.1:9090\n"
        "proxy-providers:\n  sub:\n    type: file\n    path: sub-content.yaml\n"
        "proxy-groups:\n  - name: PROXY\n    type: select\n    use:\n      - sub\n"
        "rules:\n  - MATCH,PROXY\n"
    )
    with open(os.path.join(workdir, "config.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg)


def wait_api(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"{API}/version", timeout=2).read()
            return True
        except Exception:
            time.sleep(1)
    return False


def test_node(name):
    """切换 PROXY 组到该节点，再经 7897 实拨一次。返回 (name, ok)。

    注意：provider 的 .all 为空，但代理组 /proxies/PROXY 的 .all 含全部成员；
    且 mihomo 的 /proxies/{name}/delay 对 provider 成员返回 404，只能切组后实拨。
    """
    try:
        req = urllib.request.Request(
            f"{API}/proxies/PROXY",
            method="PUT",
            data=json.dumps({"name": name}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        return name, False
    try:
        r = PROXY_OPENER.open(DELAY_URL, timeout=8)
        return name, r.status < 500
    except Exception:
        return name, False


def main():
    ap = argparse.ArgumentParser(description="从大订阅挑活节点生成 Secret 内容")
    ap.add_argument("src", help="订阅链接或本地 yaml")
    ap.add_argument("--workdir", default="node-probe")
    ap.add_argument("--need", type=int, default=150, help="攒够多少个活节点就停")
    ap.add_argument("--scan", type=int, default=600, help="最多扫描多少个节点")
    args = ap.parse_args()

    text = fetch_text(args.src)
    blocks = parse_node_blocks(text)
    by_name = dict(blocks)
    log(f"解析到 {len(blocks)} 个节点，本机启动 mihomo 测活...")
    if not blocks:
        raise SystemExit("没有节点")

    write_full_provider(blocks, args.workdir)
    write_config(args.workdir)
    exe = ensure_mihomo(args.workdir)
    logf = open(os.path.join(args.workdir, "mihomo.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([exe, "-d", args.workdir], stdout=logf, stderr=subprocess.STDOUT)
    alive = []
    try:
        if not wait_api():
            raise SystemExit("mihomo API 未就绪，看 node-probe/mihomo.log")
        # 等 provider 全部节点注册进代理组（/version 就绪 != 节点已加载）
        names = []
        for _ in range(30):
            grp = json.loads(urllib.request.urlopen(f"{API}/proxies/PROXY", timeout=5).read())
            names = grp.get("all") or []
            if len(names) > 10:
                break
            time.sleep(1)
        names = [n for n in names if n not in ("DIRECT", "REJECT", "PROXY")]
        log(f"代理组含 {len(names)} 个节点，开始逐个实拨测活...")
        for i, name in enumerate(names[: args.scan]):
            _, ok = test_node(name)
            if ok:
                alive.append(name)
                if len(alive) >= args.need:
                    break
            if (i + 1) % 50 == 0:
                log(f"  已测 {i + 1} 个，活 {len(alive)}")
        log(f"测活完成：扫描 {min(len(names), args.scan)} 个，活 {len(alive)} 个")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        logf.close()

    if not alive:
        raise SystemExit("没有任何节点可用——检查本机网络或订阅是否过期")

    # 活节点裁到 48KB 以内
    kept, size = [], len("proxies:\n")
    for name in alive:
        blk = by_name.get(name)
        if not blk:
            continue
        b = len((blk + "\n").encode("utf-8"))
        if size + b > MAX_SECRET_BYTES:
            break
        kept.append((name, blk))
        size += b

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sub_secret_content.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("proxies:\n")
        for _, blk in kept:
            f.write(blk + "\n")
    log(f"\n已写入 {out}")
    log(f"  保留 {len(kept)} 个活节点，{size} 字节（< {MAX_SECRET_BYTES} ✓）")
    log(f"  前 5 个: " + ", ".join(n for n, _ in kept[:5]))
    log("\n上传：  gh secret set CLASH_SUB_CONTENT < sub_secret_content.txt")


if __name__ == "__main__":
    main()
