from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "app_run.log"
METRICS_PATH = ROOT / "metrics.out"
HEALTH_PATH = ROOT / "health.out"
ENV_PATH = ROOT / ".env"


def fetch(url: str, retries: int = 30, delay: float = 1.0) -> str:
    last_error = ""
    for _ in range(retries):
        try:
            with urlopen(url, timeout=5) as response:  # noqa: S310
                return response.read().decode("utf-8", "ignore")
        except URLError as exc:
            last_error = str(exc)
            time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def main() -> int:
    ENV_PATH.write_text("", encoding="utf-8")
    for path in [LOG_PATH, METRICS_PATH, HEALTH_PATH]:
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    start = time.time()
    with LOG_PATH.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), stdout=log_handle, stderr=subprocess.STDOUT, env=env)
        try:
            metrics = fetch("http://127.0.0.1:8080/metrics", retries=40, delay=1.0)
            health = fetch("http://127.0.0.1:8080/health", retries=10, delay=1.0)
            METRICS_PATH.write_text(metrics, encoding="utf-8")
            HEALTH_PATH.write_text(health, encoding="utf-8")
            remaining = max(0.0, 60.0 - (time.time() - start))
            time.sleep(remaining)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
