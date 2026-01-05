# config.py
# All user-editable configuration lives here.

REFRESH_SECONDS = 5

# Risk controls (simulation)
MAX_WEIGHT_PER_STOCK = 0.15       # 15% max per stock
MAX_TURNOVER_PER_UPDATE = 0.15    # max total change per refresh

# Bearish / risk-reduced universe (15)
BEARISH_UNIVERSE = [
    "AAPL", "BRK-B", "JNJ", "PG", "KO", "PEP", "WMT", "COST", "MCD",
    "V", "MA", "UNH", "XOM", "CVX", "NEE"
]

# Bullish / risk-on universe (15)
BULLISH_UNIVERSE = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "AMD",
    "CRM", "NOW", "ASML", "TSM", "NFLX", "INTC"
]

# RSS feeds (lightweight + school-friendly). If any fail, system continues.
RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.investing.com/rss/news_25.rss",
]