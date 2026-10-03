# -*- coding: utf-8 -*-
"""linuxdo-keep-live 入口。

用法：
    python main.py           # 启动 GUI 版（默认）
    python main.py cli       # 启动无头命令行版（服务器 / Actions）
    python main.py docker    # 启动 Docker 常驻版（随机调度，每天 N 次）

GUI 版依赖 tkinter（Python 自带）；系统托盘需可选依赖：
    uv sync --extra gui
"""

import sys


def main():
    argv = sys.argv[1:]

    if argv and argv[0].lower() in ("cli", "headless"):
        from linuxdo_keep_live.cli import main as cli_main

        cli_main(argv[1:])
    elif argv and argv[0].lower() == "docker":
        from linuxdo_keep_live.docker import main as docker_main

        docker_main(argv[1:])
    else:
        try:
            from linuxdo_keep_live.gui import main as gui_main
        except ImportError as e:
            print(f"错误: 无法启动 GUI（{e}）")
            print("请确认已安装 Python 自带 tkinter；")
            print("或使用无头模式： python main.py cli -u 用户名 -p 密码")
            sys.exit(1)
        gui_main()


if __name__ == "__main__":
    main()
