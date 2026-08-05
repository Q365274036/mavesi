"""
闲鱼 CDP 守护进程
每 5 分钟检测三个号 CDP 端口是否在线，不在线则自动拉起 Edge + 注入反检测
"""
import subprocess
import time
import socket
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(r"C:\Users\邓少杰\Coze\xianyu-daemon.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("xianyu-daemon")

PORTS = {
    1: 9222,
    2: 9223,
    3: 9224,
}

PROFILE_DIR = r"C:\Users\邓少杰\Coze\edge-xianyu-profile-{n}"
STEALTH_SCRIPT = r"C:\Users\邓少杰\Coze\inject-stealth.py"


def check_port(port: int) -> bool:
    """检测端口是否在监听"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False


def launch_edge(port: int, n: int) -> bool:
    """启动 Edge 并注入反检测"""
    profile = PROFILE_DIR.format(n=n)
    try:
        subprocess.Popen(
            [
                "msedge",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info(f"号{n} (CDP {port}): Edge 已启动")
        time.sleep(5)

        # 注入反检测
        result = subprocess.run(
            ["python", STEALTH_SCRIPT, str(port)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"号{n} (CDP {port}): 反检测注入成功")
            return True
        else:
            logger.warning(f"号{n} (CDP {port}): 反检测注入失败: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"号{n} (CDP {port}): 启动失败: {e}")
        return False


def main():
    logger.info("=== 闲鱼 CDP 守护进程启动 ===")

    while True:
        for n, port in PORTS.items():
            if check_port(port):
                logger.info(f"号{n} (CDP {port}): 在线")
            else:
                logger.warning(f"号{n} (CDP {port}): 不在线，正在拉起...")
                launch_edge(port, n)

        logger.info(f"本轮检测完成，休眠 5 分钟")
        time.sleep(300)


if __name__ == "__main__":
    main()
