from __future__ import annotations

KALSHI_CATEGORY_MAP = {
    "Sports": "sports",
    "Economics": "economics",
    "Financials": "economics",
    "Companies": "economics",
    "Commodities": "economics",
    "Climate and Weather": "climate",
    "Entertainment": "entertainment",
    "Mentions": "entertainment",
    "Social": "entertainment",
    "Culture": "entertainment",
    "Elections": "politics",
    "Politics": "politics",
    "Tech": "world",
    "Health": "world",
    "Science": "world",
    "Science and Technology": "world",
    "Transportation": "world",
    "World": "world",
    "Crypto": "crypto",
    "Exotics": "exotics",
}

KALSHI_CATEGORY_MAP_CI = {k.lower(): v for k, v in KALSHI_CATEGORY_MAP.items()}

SPORTS_KEYWORDS = [
    "nba", "nfl", "mlb", "nhl", "mls", "epl", "premier league",
    "champions league", "world cup", "tennis", "atp", "wta",
    "ufc", "boxing", "mma", "f1", "formula 1", "grand prix", "nascar",
    "cricket", "rugby", "golf", "pga", "olympics",
    "super bowl", "march madness", "playoff", "world series",
    "stanley cup", "ncaa", "tournament", "mvp", "rushing yards",
    "touchdown", "home run", " vs ", " vs.", "game score", "spread",
    "wnba", "wwe", "esports",
]
POLITICS_KEYWORDS = [
    "election", "president", "presidential", "congress", "senate",
    "parliament", "prime minister", "governor", "mayor",
    "democrat", "republican", "gop", "dnc", "rnc",
    "trump", "biden", "harris", "desantis", "newsom",
    "impeachment", "indictment", "executive order", "supreme court",
    "scotus", "nomination", "confirmation", "vote",
    "approval rating", "poll", "ballot",
]
ECONOMICS_KEYWORDS = [
    "fed ", "federal reserve", "interest rate", "rate cut", "rate hike",
    "fomc", "powell", "gdp", "cpi", "ppi", "inflation",
    "jobs report", "unemployment", "payroll", "nonfarm",
    "treasury", "bond", "yield", "recession",
    "stock", "s&p", "nasdaq", "dow jones", "ipo",
    "tariff", "trade war", "debt ceiling", "housing", "mortgage", "vix",
    "gold", "silver", "oil", "crude oil", "earnings", "revenue",
]
CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "crypto", "token", "defi", "blockchain",
    "doge", "xrp", "cardano", "polkadot",
    "binance", "coinbase", "mining", "halving",
]
CLIMATE_KEYWORDS = [
    "temperature", "hurricane", "tornado", "earthquake",
    "rainfall", "snowfall", "weather", "climate",
    "record high", "record low", "heat wave", "cold snap",
    "wildfire", "flood", "drought",
]
ENTERTAINMENT_KEYWORDS = [
    "oscars", "grammy", "emmy", "golden globe", "box office",
    "streaming", "netflix", "disney", "spotify",
    "album", "movie", "tv show", "reality tv",
    "viral", "tiktok",
]


def categorize_by_keywords(title: str) -> str:
    t = (title or "").lower()
    for kw in SPORTS_KEYWORDS:
        if kw in t:
            return "sports"
    for kw in POLITICS_KEYWORDS:
        if kw in t:
            return "politics"
    for kw in ECONOMICS_KEYWORDS:
        if kw in t:
            return "economics"
    for kw in CRYPTO_KEYWORDS:
        if kw in t:
            return "crypto"
    for kw in CLIMATE_KEYWORDS:
        if kw in t:
            return "climate"
    for kw in ENTERTAINMENT_KEYWORDS:
        if kw in t:
            return "entertainment"
    return "world"


CATEGORY_EDGE = {
    "sports":        +1.0,
    "crypto":        +2.0,
    "world":         -4.0,
    "politics":       0.0,
    "economics":      0.0,
    "entertainment":  0.0,
    "climate":        0.0,
    "exotics":        0.0,
}


MICRO_MARKET_FILTERS = [
    "KXBTC15M", "KXBTC1H", "KXBTC5M", "KXBTC1M",
    "KXETH15M", "KXETH1H", "KXETH5M", "KXETH1M",
    "KXHIGHNY", "KXLOWNY", "KXHIGHCHI", "KXLOWCHI",
    "KXHIGHLA", "KXLOWLA", "KXHIGHDC", "KXLOWDC",
    "KXRAIN", "KXSNOW", "KXWIND",
]


def is_micro_market(ticker: str) -> bool:
    upper = (ticker or "").upper()
    return any(upper.startswith(f) for f in MICRO_MARKET_FILTERS)
