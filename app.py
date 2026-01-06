import streamlit as st
from streamlit_autorefresh import st_autorefresh

import db
from config import (
    REFRESH_SECONDS,
    RSS_FEEDS,
    BULLISH_UNIVERSE,
    BEARISH_UNIVERSE,
    MAX_WEIGHT_PER_STOCK,
)
from utils import utc_now_iso, clean_text
from news_scraper import fetch_rss_headlines
from sentiment_model import analyze_headline
from allocation_engine import determine_regime, build_portfolios
from prices import fetch_latest_prices


# UI for the app
def apply_dark_vibes_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1120px; }
        hr { opacity: 0.18; }

        .cm-card {
          padding: 14px 16px;
          border-radius: 18px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          margin-bottom: 12px;
          box-shadow: 0 10px 24px rgba(0,0,0,0.25);
        }
        .cm-title { font-size: 18px; font-weight: 800; margin: 0 0 6px 0; }
        .cm-sub { opacity: 0.85; margin: 0; }

        .cm-pill {
          display: inline-block;
          padding: 2px 10px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.12);
          background: rgba(255,255,255,0.03);
          font-size: 12px;
          margin-right: 6px;
          margin-bottom: 6px;
        }
        .mobile-wrap { max-width: 440px; margin-left: auto; margin-right: auto; }

        .stock-head {
          display:flex;
          justify-content:space-between;
          align-items:flex-start;
          gap: 10px;
          margin-top: 6px;
        }
        .stock-left { display:flex; gap: 10px; align-items:center; }
        .logo-dot {
          width: 42px;
          height: 42px;
          border-radius: 50%;
          background: rgba(255,255,255,0.08);
          border: 1px solid rgba(255,255,255,0.12);
          display:flex;
          align-items:center;
          justify-content:center;
          font-weight: 800;
          opacity: 0.95;
        }
        .stock-name { font-size: 16px; font-weight: 800; margin: 0; }
        .stock-sub { font-size: 12px; opacity: 0.78; margin: 0; }
        .sent-line { font-size: 13px; margin-top: 8px; }
        .sent-pos { color: #22c55e; font-weight: 700; }
        .sent-neg { color: #ef4444; font-weight: 700; }
        .sent-neu { color: #a3a3a3; font-weight: 700; }

        [data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }

        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Pill Style Label
def pill(text: str) -> str:
    return f'<span class="cm-pill">{text}</span>'


# Convert portfolio weights to rows
def weights_to_rows(weights: dict, prices: dict) -> list:
    rows = []
    for ticker, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        price = prices.get(ticker)
        rows.append(
            {
                "Ticker": ticker,
                "Weight": round(float(weight), 4),
                "Price (approx)": None if price is None else round(float(price), 2),
            }
        )
    return rows


# Rebalance portfolio by fixing one asset and scaling the rest
def rebalance_to_target(weights: dict, ticker: str, target_weight: float) -> dict:
    if ticker not in weights:
        return weights

    cap = float(MAX_WEIGHT_PER_STOCK)
    target_weight = max(0.0, min(float(target_weight), cap))

    keys = list(weights.keys())
    if len(keys) == 1:
        return {ticker: 1.0}

    others = [k for k in keys if k != ticker]
    other_total_old = sum(weights[k] for k in others)
    remaining = 1.0 - target_weight

    if other_total_old <= 1e-9:
        eq = remaining / len(others)
        out = {k: eq for k in others}
        out[ticker] = target_weight
        return out

    scale = remaining / other_total_old
    out = {k: weights[k] * scale for k in others}
    out[ticker] = target_weight

    s = sum(out.values())
    if s > 0:
        out = {k: v / s for k, v in out.items()}
    return out


# Display sentiment from related headlines or regime
def infer_asset_sentiment(analyses: list, ticker: str, regime: str) -> str:
    ticker_l = ticker.lower()
    hits = []
    for a in analyses:
        title_l = (a.get("title") or "").lower()
        if ticker_l in title_l:
            hits.append(a)

    if not hits:
        return f"Market: {regime}"

    hits.sort(key=lambda x: float(x.get("impact_score", 0.0)), reverse=True)
    return hits[0].get("label", f"Market: {regime}")


# Map sentiment label to CSS class
def sentiment_class(label: str) -> str:
    label_l = (label or "").lower()
    if "positive" in label_l:
        return "sent-pos"
    if "negative" in label_l:
        return "sent-neg"
    return "sent-neu"


# Safely choose a default index for selectboxes
def default_index(options: list, preferred: str) -> int:
    try:
        return options.index(preferred)
    except ValueError:
        return 0


# Main Streamlit application entry point to display info
def main() -> None:
    st.set_page_config(page_title="News-Driven Portfolio Simulator", layout="wide")
    apply_dark_vibes_css()

    st_autorefresh(interval=int(REFRESH_SECONDS * 1000), key="auto_refresh")
    db.init_db()

    if "bull_weights" not in st.session_state:
        st.session_state.bull_weights = {}
    if "bear_weights" not in st.session_state:
        st.session_state.bear_weights = {}

    now = utc_now_iso()

    st.title("News-Driven Portfolio Simulator")
    st.caption("Simulation-only: RSS news → sentiment/impact → explainable allocation rules. No real trading.")

    headlines = fetch_rss_headlines(RSS_FEEDS, limit_total=18)
    if not headlines:
        headlines = [
            {"title": "Markets mixed as investors await inflation data", "source": "Fallback", "published": ""},
            {"title": "Tech stocks rise after strong earnings guidance", "source": "Fallback", "published": ""},
            {"title": "Oil climbs on geopolitical tensions", "source": "Fallback", "published": ""},
        ]

    analyses = []
    for h in headlines:
        title = clean_text(h.get("title", ""))
        source = clean_text(h.get("source", ""))
        published = clean_text(h.get("published", ""))

        news_id = db.insert_news(fetched_at=now, title=title, source=source, published=published)

        a = analyze_headline(title)
        db.insert_sentiment(
            news_id=news_id,
            analyzed_at=now,
            label=a.label,
            compound=a.compound,
            impact_label=a.impact_label,
            impact_score=a.impact_score,
            category=a.category,
        )

        analyses.append(
            {
                "title": title,
                "source": source,
                "published": published,
                "label": a.label,
                "compound": a.compound,
                "impact_label": a.impact_label,
                "impact_score": a.impact_score,
                "category": a.category,
            }
        )

    regime, reason = determine_regime(analyses)

    base_bull, base_bear = build_portfolios(
        bullish_universe=BULLISH_UNIVERSE,
        bearish_universe=BEARISH_UNIVERSE,
        regime=regime,
        prev_bull=st.session_state.bull_weights,
        prev_bear=st.session_state.bear_weights,
    )

    if not st.session_state.bull_weights:
        st.session_state.bull_weights = base_bull
    if not st.session_state.bear_weights:
        st.session_state.bear_weights = base_bear

    all_tickers = sorted(set(BULLISH_UNIVERSE + BEARISH_UNIVERSE))
    prices = fetch_latest_prices(all_tickers)

    st.markdown(
        f"""
        <div class="cm-card">
            {pill("Simulation Only")}
            {pill(f"Refresh: {REFRESH_SECONDS}s")}
            {pill(f"Regime: {regime}")}
            {pill(f"UTC: {now}")}
            <div style="margin-top:6px; opacity:0.9;">
                <b>Decision:</b> {reason}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1])

    with left:
        st.subheader("Latest News (Analysed)")
        for a in analyses[:12]:
            st.markdown(
                f"- **{a['title']}**\n"
                f"  - *{a['source']}*  |  Category: `{a['category']}`\n"
                f"  - Sentiment: `{a['label']}` (compound {a['compound']:+.2f})  |  Impact: `{a['impact_label']}`"
            )

    with right:
        st.markdown('<div class="mobile-wrap">', unsafe_allow_html=True)
        st.markdown('<div class="cm-card">', unsafe_allow_html=True)

        st.markdown('<p class="cm-title">Reallocate Asset Based on Sentiment</p>', unsafe_allow_html=True)
        st.markdown('<p class="cm-sub">Adjust a simulated portfolio weight and confirm.</p>', unsafe_allow_html=True)

        portfolio_options = ["Bullish (Risk-On)", "Bearish (Risk-Reduced)"]
        portfolio_choice = st.selectbox(
            "Portfolio",
            portfolio_options,
            index=default_index(portfolio_options, "Bullish (Risk-On)"),
        )

        if portfolio_choice.startswith("Bullish"):
            active_key = "bull_weights"
            universe = BULLISH_UNIVERSE
        else:
            active_key = "bear_weights"
            universe = BEARISH_UNIVERSE

        default_asset = "TSLA" if "TSLA" in universe else universe[0]
        ticker = st.selectbox(
            "Asset",
            universe,
            index=default_index(universe, default_asset),
        )

        active_weights = dict(st.session_state[active_key])
        current_w = float(active_weights.get(ticker, 0.0))
        price = prices.get(ticker, None)

        asset_sent = infer_asset_sentiment(analyses, ticker, regime)
        sent_cls = sentiment_class(asset_sent)

        st.markdown(
            f"""
            <div class="stock-head">
              <div class="stock-left">
                <div class="logo-dot">{ticker[:1]}</div>
                <div>
                  <p class="stock-name">{ticker}</p>
                  <p class="stock-sub">Current share: {current_w*100:.1f}%</p>
                </div>
              </div>
              <div style="text-align:right;">
                <p class="stock-sub">Price</p>
                <p class="stock-name">{('N/A' if price is None else round(float(price), 2))}</p>
              </div>
            </div>
            <div class="sent-line">
              <span style="opacity:0.78;">Sentiment:&nbsp;</span>
              <span class="{sent_cls}">{asset_sent}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")

        max_slider = min(0.20, float(MAX_WEIGHT_PER_STOCK))
        target_w = st.slider(
            f"{ticker} target weight",
            min_value=0.0,
            max_value=float(max_slider),
            value=float(min(current_w, max_slider)),
            step=0.005,
            format="%.3f",
        )

        st.write(f"Target: **{target_w*100:.1f}%**  (From **{current_w*100:.1f}%)**")

        if st.button("CONFIRM REALLOCATION", type="primary"):
            updated = rebalance_to_target(active_weights, ticker, target_w)
            st.session_state[active_key] = updated

            db.save_portfolio_snapshot(now, regime, f"{portfolio_choice}_MANUAL", updated)
            db.log_decision(
                now,
                regime,
                f"Manual reallocation: set {ticker} to {target_w*100:.1f}% in {portfolio_choice} (was {current_w*100:.1f}%).",
            )
            st.success("Reallocation applied (simulation).")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("Portfolio Weights")
        tab1, tab2 = st.tabs(["Bullish", "Bearish"])
        with tab1:
            st.dataframe(weights_to_rows(st.session_state.bull_weights, prices), use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(weights_to_rows(st.session_state.bear_weights, prices), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Decision Log")
    for d in db.get_recent_decisions(limit=10):
        st.markdown(f"- `{d['created_at']}` **{d['regime']}** — {d['message']}")


if __name__ == "__main__":
    main()
