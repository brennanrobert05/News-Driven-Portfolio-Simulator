# prices.py
# Pulls delayed/approx market prices for display only (no trading).
import yfinance as yf
import pandas as pd

def fetch_latest_prices(tickers):
    if not tickers:
        return {}

    try:
        df = yf.download(
            tickers=tickers,
            period="1d",
            interval="5m",
            progress=False,
            threads=True,
            group_by="ticker",
            auto_adjust=True,
        )

        prices = {}

        # Multi-index = multiple tickers
        if isinstance(df.columns, pd.MultiIndex):
            for t in tickers:
                if (t, "Close") in df.columns:
                    s = df[(t, "Close")].dropna()
                    if len(s) > 0:
                        prices[t] = float(s.iloc[-1])
        else:
            # Single ticker case
            if "Close" in df.columns:
                s = df["Close"].dropna()
                if len(s) > 0:
                    prices[tickers[0]] = float(s.iloc[-1])

        return prices

    except Exception:
        return {}
