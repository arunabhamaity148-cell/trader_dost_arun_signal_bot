from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from trader_dost_arun.backtest.engine import BacktestEngine


def build_html(results: dict) -> str:
    sections = ["<html><body><h1>Trader Dost Arun Elite Backtest</h1>"]
    for strategy, result in results.items():
        metrics = result.metrics()
        points = ",".join(f"[{idx},{equity:.6f}]" for idx, equity in enumerate(result.equity_curve))
        sections.append(f"<h2>{strategy}</h2>")
        sections.append("<ul>" + "".join(f"<li>{k}: {v}</li>" for k, v in metrics.items() if k != 'regimes') + "</ul>")
        sections.append(f"<div data-equity='{points}'></div>")
        sections.append(f"<pre>{metrics['regimes']}</pre>")
    sections.append("</body></html>")
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--strategies", default="all")
    parser.add_argument("--db-path", default="./data/historical.sqlite3")
    args = parser.parse_args()
    engine = BacktestEngine(db_path=args.db_path)
    results = engine.run(args.symbol, days=args.days, strategies=args.strategies.split(","))
    output_dir = Path("./data/backtest_reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    html_path = output_dir / f"{timestamp}.html"
    csv_path = output_dir / f"{timestamp}.csv"
    engine.export_equity_curve(results, csv_path)
    html_path.write_text(build_html(results), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
