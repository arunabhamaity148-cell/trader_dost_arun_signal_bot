import json
from pathlib import Path

from trader_dost_arun.newsguard.llm_classifier import LLMNewsClassifier


def test_fallback_classifier_detects_incident(tmp_path: Path):
    clf = LLMNewsClassifier(db_path=tmp_path / "cache.sqlite3", command=["/bin/false"])
    result = clf.classify_batch([{"title": "Exchange hack incident", "summary": "withdrawals halted", "symbols": ["BTC"]}])[0]
    assert result["category"] == "incident"


def test_cache_reuses_previous_result(tmp_path: Path):
    clf = LLMNewsClassifier(db_path=tmp_path / "cache.sqlite3", command=["/bin/false"])
    event = {"title": "Macro CPI print", "summary": "inflation", "symbols": ["BTC"]}
    first = clf.classify_batch([event])[0]
    second = clf.classify_batch([event])[0]
    assert first == second


def test_batch_parses_mock_json(monkeypatch, tmp_path: Path):
    clf = LLMNewsClassifier(db_path=tmp_path / "cache.sqlite3")

    class Result:
        stdout = json.dumps([{"category": "partnership", "severity_0_to_1": 0.5, "sentiment_-1_to_1": 0.3, "affected_symbols": ["ETH"], "time_horizon_minutes": 60, "confidence": 0.8}])

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    result = clf.classify_batch([{"title": "New partnership", "summary": "launch", "symbols": ["ETH"]}])[0]
    assert result["category"] == "partnership"
