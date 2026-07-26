from __future__ import annotations

import argparse
import html
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go

from trader_dost_arun.backtest.engine import BacktestEngine

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def _metrics_table(metrics: dict) -> str:
    rows = []
    for key, value in metrics.items():
        if key == "regimes":
            continue
        display = f"{value:.6f}" if isinstance(value, float) else html.escape(str(value))
        rows.append(f"<tr><th>{html.escape(str(key))}</th><td>{display}</td></tr>")
    return (
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<thead><tr><th>Metric</th><th>Value</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _regime_table(regimes: dict[str, dict[str, float]]) -> str:
    if not regimes:
        return "<p>No regime breakdown available.</p>"
    rows = []
    for regime_key, values in regimes.items():
        rows.append(
            "<tr>"
            f"<td>{html.escape(regime_key)}</td>"
            f"<td>{values.get('count', 0.0):.0f}</td>"
            f"<td>{values.get('win_rate', 0.0):.4f}</td>"
            f"<td>{values.get('expectancy', 0.0):.6f}</td>"
            "</tr>"
        )
    return (
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<thead><tr><th>Regime</th><th>Count</th><th>Win Rate</th><th>Expectancy</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _equity_chart(strategy: str, equity_curve: list[float]) -> str:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(range(len(equity_curve))),
            y=equity_curve,
            mode="lines",
            name=strategy,
            line={"width": 3},
        )
    )
    fig.update_layout(
        title=f"{strategy} Equity Curve",
        xaxis_title="Step",
        yaxis_title="Equity",
        template="plotly_white",
        height=420,
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_html(results: dict) -> str:
    sections = [
        "<html>",
        "<head>",
        "<meta charset='utf-8'>",
        "<title>Trader Dost Arun Elite Backtest</title>",
        f"<script src='{PLOTLY_CDN}'></script>",
        "</head>",
        "<body>",
        "<h1>Trader Dost Arun Elite Backtest</h1>",
    ]
    if not results:
        sections.append("<p>No trades found for the selected symbol/date range.</p>")
        sections.append(_equity_chart("No Data", [1.0]))
        sections.append("</body></html>")
        return "\n".join(sections)
    for strategy, result in results.items():
        metrics = result.metrics()
        sections.append(f"<section><h2>{html.escape(str(strategy))}</h2>")
        sections.append("<h3>Performance Metrics</h3>")
        sections.append(_metrics_table(metrics))
        sections.append("<h3>Equity Curve</h3>")
        sections.append(_equity_chart(str(strategy), result.equity_curve))
        sections.append("<h3>Regime Breakdown</h3>")
        sections.append(_regime_table(metrics.get("regimes", {})))
        sections.append("</section><hr/>")
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
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    html_path = output_dir / f"{timestamp}.html"
    csv_path = output_dir / f"{timestamp}.csv"
    engine.export_equity_curve(results, csv_path)
    html_path.write_text(build_html(results), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
