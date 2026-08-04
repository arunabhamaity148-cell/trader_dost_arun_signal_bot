from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_text(name: str) -> str:
    path = ROOT / name
    return path.read_text(encoding="utf-8") if path.exists() else "[missing]"


def main() -> None:
    pytest_output = read_text("pytest_output.txt").strip()
    log_excerpt = read_text("app_log_last30.txt").strip()
    banned = read_text("banned_tokens.txt").strip() or "No Traceback / AttributeError / KeyError / CRITICAL found in app_run.log"
    connected = read_text("connected_venues.txt").strip()
    metrics = read_text("metrics.out").strip()
    health = read_text("health.out").strip()
    backtest_path = read_text("backtest_path.txt").strip()
    backtest_html = (ROOT / backtest_path).read_text(encoding="utf-8") if backtest_path and (ROOT / backtest_path).exists() else ""
    plotly_confirmation = "plotly-graph-div present" if "plotly-graph-div" in backtest_html else "plotly-graph-div NOT found"
    telegram = read_text("telegram_sample.txt").strip()

    report = f"""# VERIFICATION REPORT

## 1) Pytest
```text
{pytest_output}
```

## 2) 60-second bot run with empty `.env`
### Connected venues observed
```text
{connected}
```

### Last 30 log lines
```text
{log_excerpt}
```

### Grep confirmation for banned log tokens
```text
{banned}
```

## 3) /metrics response while bot was running
```text
{metrics}
```

## 4) /health response while bot was running
```text
{health}
```

## 5) Backtest HTML verification
- HTML path: `{backtest_path}`
- Plotly confirmation: **{plotly_confirmation}**

## 6) Telegram formatter sample output
```text
{telegram}
```
"""
    (ROOT / "VERIFICATION_REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
