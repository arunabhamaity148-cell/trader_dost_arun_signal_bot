from __future__ import annotations

import re
from dataclasses import dataclass

DERIVATIVE_VENUES = {"binance", "bybit", "okx", "hyperliquid", "deribit"}
PERPETUAL_MARKERS = {"PERP", "PERPETUAL", "SWAP"}
USD_EQUIVALENT_QUOTES = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDE", "USDD"}
KNOWN_QUOTES = tuple(sorted(USD_EQUIVALENT_QUOTES | {"BTC", "ETH", "EUR", "JPY", "TRY", "BRL"}, key=len, reverse=True))
DATE_TOKEN = re.compile(r"^\d{1,2}[A-Z]{3}\d{2,4}$")
NUMERIC_TOKEN = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    raw_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    quote_class: str

    @property
    def canonical_symbol(self) -> str:
        return f"{self.base_asset}:{self.quote_class}:{self.instrument_type}"


def _quote_class(quote: str) -> str:
    quote = quote.upper().strip()
    if not quote:
        return "usd"
    if quote in USD_EQUIVALENT_QUOTES:
        return "usd"
    return quote.lower()


def _split_flat_symbol(symbol: str) -> tuple[str, str]:
    upper = symbol.upper().strip()
    for quote in KNOWN_QUOTES:
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)], quote
    return upper, ""


def normalize_instrument(venue: str, symbol: str) -> InstrumentIdentity:
    raw_symbol = symbol.strip().upper()
    normalized = raw_symbol.replace("/", "-")
    tokens = [token for token in normalized.split("-") if token]
    venue_key = venue.strip().lower()
    base_asset = ""
    quote_asset = ""
    instrument_type = "unknown"

    if len(tokens) >= 4 and DATE_TOKEN.match(tokens[1]) and NUMERIC_TOKEN.match(tokens[2]) and tokens[3] in {"C", "P"}:
        base_asset = tokens[0]
        instrument_type = "option"
    elif len(tokens) >= 2 and tokens[-1] in PERPETUAL_MARKERS:
        base_asset = tokens[0]
        instrument_type = "perpetual"
        if len(tokens) >= 3 and tokens[-2] not in PERPETUAL_MARKERS:
            quote_asset = tokens[-2]
    elif len(tokens) >= 2 and DATE_TOKEN.match(tokens[-1]):
        base_asset = tokens[0]
        instrument_type = "future"
        if len(tokens) >= 3:
            quote_asset = tokens[-2]
    elif len(tokens) >= 2:
        base_asset = tokens[0]
        quote_asset = tokens[-1]
        instrument_type = "perpetual" if venue_key in DERIVATIVE_VENUES else "spot"
    else:
        base_asset, quote_asset = _split_flat_symbol(raw_symbol)
        if venue_key in DERIVATIVE_VENUES and quote_asset:
            instrument_type = "perpetual"
        elif quote_asset:
            instrument_type = "spot"

    if not quote_asset and instrument_type in {"perpetual", "future", "option"}:
        quote_asset = "USD"
    if not base_asset:
        base_asset = raw_symbol
    quote_class = _quote_class(quote_asset)
    return InstrumentIdentity(
        raw_symbol=raw_symbol,
        base_asset=base_asset,
        quote_asset=quote_asset,
        instrument_type=instrument_type,
        quote_class=quote_class,
    )
