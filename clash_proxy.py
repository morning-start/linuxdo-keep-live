# -*- coding: utf-8 -*-
"""Clash 代理编排：订阅解析 -> mihomo 配置生成/启动 -> 节点自检。

把之前塞在 workflow 里的几十行 bash 收敛成一个可本地调试的 Python 脚本。
workflow 里只剩一行调用；本机也能直接跑（mihomo 有 Windows 版）：

    # 本机完整验证（下载 mihomo、起代理、逐节点探测 linux.do）
    python clash_proxy.py --sub-content-file sub_secret_content.txt
    python clash_proxy.py --sub-url https://你的订阅链接

    # 只生成配置不起代理（调试订阅解析）
    python clash_proxy.py --sub-url ... --prepare-only --workdir ./mihomo-test

    # 只把订阅解析结果打印出来（配合 prepare_sub_secret.py 生成 Secret）
    python clash_proxy.py --sub-url ... --extract-only

环境变量（GitHub Actions 用，本机调试也可用）:
    CLASH_SUB           订阅链接（https://）
    CLASH_SUB_CONTENT   订阅 YAML 内容（优先于 CLASH_SUB）

退出码:
    0 = 代理就绪且自检通过（PROXY_PASS=1）
    2 = 代理未就绪/自检未通过（降级直连，不算致命错误）
    1 = 参数错误等硬失败
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

MIHOMO_VER = "v1.19.32"
MIHOMO_BASE = f"https://github.com/MetaCubeX/mihomo/releases/download/{MIHOMO_VER}"

# 占位节点关键词（机场塞在订阅头部的展示节点，不能转发流量）
PLACEHOLDER_RE = re.compile(
    r"剩余|流量|官网|到期|重置|expire|traffic|套餐|防失联|版本|群|tg|telegram",
    re.I,
)

# 资产名前缀（按平台）
ASSETS = {
    ("win32", "amd64"): f"mihomo-windows-amd64-{MIHOMO_VER}.zip",
    ("linux", "x86_64"): f"mihomo-linux-amd64-{MIHOMO_VER}.gz",
    ("linux", "aarch64"): f"mihomo-linux-arm64-{MIHOMO_VER}.gz",
    ("darwin", "arm64"): f"mihomo-darwin-arm64-{MIHOMO_VER}.gz",
    ("darwin", "x86_64"): f"mihomo-darwin-amd64-{MIHOMO_VER}.gz",
}


def log(msg):
    print(msg, flush=True)


# Windows 控制台默认 GBK，无法输出 ✅/❌ 等字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def download(url, dest):
    """流式下载（带进度），避免 CI 上静默卡死。"""
    log(f"下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "clash-verge/v1.7.7"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                log(f"  {done * 100 // total}% ({done // 1048576}MB/{total // 1048576}MB)")
    return dest


def fetch_subscription(args) -> str:
    """拿到订阅 YAML 文本：文件 > 环境变量 > 链接。"""
    if args.sub_content_file:
        text = open(args.sub_content_file, encoding="utf-8", errors="replace").read()
        log(f"模式: 本地订阅文件 {args.sub_content_file}")
    elif os.environ.get("CLASH_SUB_CONTENT"):
        text = os.environ["CLASH_SUB_CONTENT"]
        log("模式: CLASH_SUB_CONTENT（订阅内容直接注入，不经网络）")
    elif os.environ.get("CLASH_SUB"):
        url = os.environ["CLASH_SUB"]
        if url.startswith("clash://"):
            raise SystemExit(
                "CLASH_SUB 是 clash:// 一键导入链接，请改填原始 https:// 订阅地址，"
                "或改用 CLASH_SUB_CONTENT 直接贴内容"
            )
        log(f"模式: 订阅链接 {url[:50]}...")
        req = urllib.request.Request(url, headers={"User-Agent": "clash-verge/v1.7.7"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            raise SystemExit(
                f"订阅链接拉取失败: {e}\n"
                "机场的 Cloudflare 大概率拦截了本机/CI 的 IP，"
                "请改用 CLASH_SUB_CONTENT（本机浏览器下载订阅 yaml 后贴内容）"
            )
    else:
        raise SystemExit("未提供订阅：设 CLASH_SUB / CLASH_SUB_CONTENT 或传 --sub-content-file")

    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")

    # base64 订阅（v2ray 通用格式）自动解码
    if "proxies:" not in text:
        try:
            compact = "".join(text.split())
            decoded = base64.b64decode(
                compact.replace("-", "+").replace("_", "/") + "=" * (-len(compact) % 4),
                validate=True,
            ).decode("utf-8")
            if "proxies:" in decoded:
                log("检测到 base64 订阅，已解码")
                text = decoded
        except Exception:
            pass

    if "proxies:" not in text:
        raise SystemExit("订阅内容无效：既不是含 proxies: 的 YAML，也不是 base64 订阅")
    return text


def write_provider_file(text: str, workdir: str) -> str:
    """把订阅规整成 mihomo file provider 可用的 yaml（只保留 proxies: 列表）。

    丢掉 dns/rules/proxy-groups 等顶层键，避免完整订阅里与我们的最小配置冲突
    （如订阅自带 port/mixed-port 会让 mihomo 端口配置失效）。
    """
    lines = text.split("\n")
    out, in_proxies = [], False
    for line in lines:
        if re.match(r"^proxies:\s*$", line):
            in_proxies = True
            out.append(line)
            continue
        if in_proxies:
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            if line.strip():
                out.append(line)
    if not out:
        raise SystemExit("订阅里没有找到 proxies: 节点列表")

    path = os.path.join(workdir, "sub-content.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    n = sum(1 for l in out if re.match(r"\s*-\s*\{?\s*name:", l))
    log(f"节点文件已写入: {path}（{n} 个节点，{len(chr(10).join(out))} 字符）")
    return path


def ensure_mihomo(workdir: str) -> str:
    """确保 mihomo 内核可用，返回可执行文件路径。"""
    name = "mihomo.exe" if sys.platform == "win32" else "mihomo"
    # zip 解包后的实际文件名可能是 mihomo-windows-amd64.exe 等，统一规范为 mihomo.exe
    for root, _, files in os.walk(workdir):
        if name in files:
            return os.path.join(root, name)

    key = (sys.platform, os.uname().machine if sys.platform != "win32" else "amd64")
    asset = ASSETS.get(key)
    if not asset:
        raise SystemExit(f"不支持的平台: {key}")
    url = f"{MIHOMO_BASE}/{asset}"
    arch = os.path.join(workdir, asset)
    exe = os.path.join(workdir, name)
    download(url, arch)

    if asset.endswith(".zip"):
        shutil.unpack_archive(arch, workdir)
        # zip 里的文件名带平台后缀（mihomo-windows-amd64.exe），找到并规范成 mihomo.exe
        found = None
        for root, _, files in os.walk(workdir):
            for f in files:
                if f.endswith(".exe") and f.startswith("mihomo"):
                    found = os.path.join(root, f)
                    break
        if not found:
            raise SystemExit("zip 解包后找不到 mihomo 可执行文件")
        if found != exe:
            shutil.move(found, exe)
    else:
        import gzip

        with gzip.open(arch, "rb") as src, open(exe, "wb") as dst:
            dst.write(src.read())
    try:
        os.chmod(exe, 0o755)
    except OSError:
        pass
    if os.path.exists(arch):
        os.remove(arch)
    ver = subprocess.run([exe, "-v"], capture_output=True, text=True).stdout.splitlines()
    log("mihomo: " + (ver[0] if ver else "?"))
    return exe


def write_config(workdir: str, provider_path: str):
    cfg = f"""mixed-port: 7897
allow-lan: false
mode: rule
log-level: info
external-controller: 127.0.0.1:9090
profile:
  store-selected: false
proxy-providers:
  sub:
    type: file
    path: {os.path.basename(provider_path)}
    interval: 86400
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300
proxy-groups:
  - name: PROXY
    type: select
    use:
      - sub
rules:
  - MATCH,PROXY
"""
    path = os.path.join(workdir, "config.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg)
    return path


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:9090{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def probe_linuxdo(proxy="http://127.0.0.1:7897", timeout=20):
    """经代理探测 linux.do；返回 (状态码, cf挑战标记)。

    状态码含义：
        200        直达
        403+cf标记 Cloudflare 挑战页——节点转发正常，浏览器可以过挑战
        429        限流
        000        连不通（节点死/超时）
    """
    req = urllib.request.Request(
        "https://linux.do/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            )
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    try:
        r = opener.open(req, timeout=timeout)
        return str(r.status), r.headers.get("cf-mitigated") or ""
    except urllib.error.HTTPError as e:
        return str(e.code), e.headers.get("cf-mitigated") or ""
    except Exception:
        return "000", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workdir", default="mihomo-work", help="工作目录（默认 ./mihomo-work）")
    ap.add_argument("--sub-content-file", help="订阅内容文件（本地调试用）")
    ap.add_argument("--sub-url", help="订阅链接（覆盖环境变量 CLASH_SUB）")
    ap.add_argument("--prepare-only", action="store_true", help="只生成配置不起代理")
    ap.add_argument("--extract-only", action="store_true", help="只打印订阅解析结果")
    ap.add_argument("--probe-nodes", type=int, default=10, help="最多探测节点数（默认 10）")
    args = ap.parse_args()

    if args.sub_url:
        os.environ["CLASH_SUB"] = args.sub_url

    os.makedirs(args.workdir, exist_ok=True)

    # 1. 订阅解析
    sub_text = fetch_subscription(args)
    if args.extract_only:
        print(sub_text)
        return
    provider = write_provider_file(sub_text, args.workdir)

    # 2. 配置生成
    write_config(args.workdir, provider)
    if args.prepare_only:
        log(f"配置已生成于 {args.workdir}（--prepare-only，不启动）")
        return

    # 3. mihomo 就绪（本机已装则跳过下载）
    exe = ensure_mihomo(args.workdir)
    logf = open(os.path.join(args.workdir, "mihomo.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [exe, "-d", args.workdir], stdout=logf, stderr=subprocess.STDOUT
    )

    success = False  # 自检通过才保留进程（CLASH_KEEP_RUNNING=1 时供后续步骤使用）
    try:
        ok = False
        for _ in range(15):
            if proc.poll() is not None:
                log("mihomo 进程已退出，日志:")
                log(open(os.path.join(args.workdir, "mihomo.log"), encoding="utf-8").read())
                sys.exit(2)
            if api("/version"):
                log("mihomo 已启动（API 就绪）")
                ok = True
                break
            time.sleep(2)
        if not ok:
            log("mihomo 启动超时")
            sys.exit(2)

        # 4. 节点发现与自检（动态发现 provider，两级兜底）
        # 注意 mihomo schema：provider 详情的节点在 "proxies" 字段，
        # 代理组（/proxies/NAME）的节点在 "all" 字段——不能混用！
        # 同时 providers 列表接口里 "proxies" 是摘要（内置组也有），真实
        # 节点数要用 File/HTTP vehicle 的 provider 详情确认，优先选非 Compatible。
        providers = api("/providers/proxies") or {}
        plist = providers.get("providers") or {}
        # 按优先级排序：File/HTTP（真订阅）> 其他非 compatible
        ordered = sorted(
            ((k, v) for k, v in plist.items() if k != "compatible"),
            key=lambda kv: 0 if (kv[1] or {}).get("vehicleType") in ("File", "HTTP") else 1,
        )
        nodes = []
        for name, meta in ordered:
            if (meta or {}).get("vehicleType") == "Compatible":
                continue
            detail = api(f"/providers/proxies/{name}") or {}
            raw = detail.get("proxies") or detail.get("all") or []
            got = [p.get("name", "") for p in raw]
            # Compatible 内置 provider 也有 3 个假节点（DIRECT/REJECT/PROXY），
            # 只有「过滤占位后还有富余」的才算真订阅
            real_cnt = sum(1 for n in got if n and not PLACEHOLDER_RE.search(n))
            if got and (real_cnt > 0 or len(got) > 5):
                nodes = got
                log(f"provider: {name}（vehicle={meta.get('vehicleType')}），节点 {len(nodes)} 个")
                break
        if not nodes:
            group = api("/proxies/PROXY") or {}
            nodes = [p.get("name", "") for p in (group.get("all") or [])]
            log(f"从 PROXY 组取到 {len(nodes)} 个节点")

        real = [n for n in nodes if n and not PLACEHOLDER_RE.search(n)]
        log(f"占位过滤后真实节点 {len(real)}/{len(nodes)} 个")
        if not real:
            log("过滤后没有真实节点，退回全量")
            real = [n for n in nodes if n]

        passed = None
        for i, node in enumerate(real[: args.probe_nodes]):
            api("/proxies/PROXY", method="PUT", body={"name": node})
            time.sleep(1)
            code, cf = probe_linuxdo()
            tag = " [CF挑战]" if cf else ""
            log(f"节点#{i} [{node}] 访问 linux.do -> HTTP {code}{tag}")
            # 仅 000（连不通/超时）与 429（限流）算节点不可用；
            # 其余任何响应（200 直达、403+CF挑战页、401/5xx 等）都说明
            # 节点转发正常且没被限流——浏览器拿到页面后可以自己过挑战
            if code not in ("000", "429"):
                passed = node
                break
            if code == "429":
                log("  └ 429 限流，换下一个节点")

        if passed:
            log(f"✅ 代理自检通过（节点: {passed}），PROXY_PASS=1")
            success = True
            sys.exit(0)
        log("❌ 所有探测节点均无法访问 linux.do，PROXY_PASS=0")
        log("---- mihomo 最近日志 ----")
        log(open(os.path.join(args.workdir, "mihomo.log"), encoding="utf-8").read()[-2000:])
        sys.exit(2)
    finally:
        # Actions 场景：仅自检通过且显式要求时常驻（供浏览步骤走 127.0.0.1:7897），
        # 其余情况一律回收进程
        keep = success and bool(os.environ.get("CLASH_KEEP_RUNNING"))
        if not keep:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            logf.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
