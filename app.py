# app.py
# Streamlit dashboard with:
# - Dark mobile-card UI vibe
# - RSS news ingestion
# - Sentiment + impact analysis
# - Rule-based Bullish/Bearish portfolios
# - Manual reallocation feature (slider + confirm, simulation-only)
# - Demo defaults: Bullish + TSLA selected automatically (if present)
# - IMPROVED: Smart decision logging with turnover gating and deduplication


import streamlit as st
from streamlit_autorefresh import st_autorefresh
import hashlib
import json


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


# ----------------------------
# Decision Log Helpers
# ----------------------------

def compute_turnover(old_weights: dict, new_weights: dict) -> float:
    """
    Calculate portfolio turnover = sum of absolute weight changes.
    Returns a value between 0.0 and 2.0 (full portfolio flip).
    """
    all_tickers = set(old_weights.keys()) | set(new_weights.keys())
    total_change = 0.0
    for ticker in all_tickers:
        old_w = old_weights.get(ticker, 0.0)
        new_w = new_weights.get(ticker, 0.0)
        total_change += abs(new_w - old_w)
    return total_change


def get_top_changes(old_weights: dict, new_weights: dict, top_n: int = 3) -> list:
    """
    Return top N tickers by absolute weight change.
    Returns list of tuples: (ticker, old_weight, new_weight, delta)
    """
    all_tickers = set(old_weights.keys()) | set(new_weights.keys())
    changes = []
    for ticker in all_tickers:
        old_w = old_weights.get(ticker, 0.0)
        new_w = new_weights.get(ticker, 0.0)
        delta = new_w - old_w
        if abs(delta) > 0.0001:  # Filter noise
            changes.append((ticker, old_w, new_w, delta))
    
    changes.sort(key=lambda x: abs(x[3]), reverse=True)
    return changes[:top_n]


def get_relevant_headlines(analyses: list, top_n: int = 2) -> list:
    """
    Get top N most impactful relevant headlines.
    Returns list of dicts with title, source, label, impact_score.
    """
    # Filter for high-impact headlines
    relevant = [
        a for a in analyses 
        if a.get('impact_score', 0) >= 0.40 and a.get('label') in ('Positive', 'Negative')
    ]
    
    # Sort by impact score
    relevant.sort(key=lambda x: x.get('impact_score', 0), reverse=True)
    
    return relevant[:top_n]


def create_decision_hash(regime: str, weights: dict, timestamp: str) -> str:
    """
    Create a stable hash for deduplication.
    Hash is based on regime + rounded weights + timestamp (to minute precision).
    This prevents duplicate logs from Streamlit reruns within the same minute.
    """
    # Round timestamp to minute to allow deduplication within same minute
    ts_minute = timestamp[:16]  # YYYY-MM-DDTHH:MM
    
    # Round weights to 3 decimal places for stability
    rounded_weights = {k: round(v, 3) for k, v in sorted(weights.items())}
    
    # Create hash
    hash_input = f"{regime}|{json.dumps(rounded_weights)}|{ts_minute}"
    return hashlib.md5(hash_input.encode()).hexdigest()


def should_log_decision(
    old_weights: dict,
    new_weights: dict,
    decision_hash: str,
    min_turnover: float = 0.01,
    high_impact_news: bool = False
) -> bool:
    """
    Gate function: Only log if this is a meaningful, unique decision.
    
    Returns True if:
    1. Turnover >= min_turnover (default 1%), OR
    2. High-impact relevant news triggered the change
    3. AND this decision hash hasn't been logged recently
    
    This prevents spam from Streamlit reruns by:
    - Checking turnover to ensure real portfolio changes
    - Tracking logged hashes to prevent duplicate entries
    - Using minute-precision timestamps for stable hashing
    """
    # Check if we've logged this decision hash in session
    if 'logged_decision_hashes' not in st.session_state:
        st.session_state.logged_decision_hashes = set()
    
    # Deduplication: Prevent same decision from being logged multiple times on reruns
    if decision_hash in st.session_state.logged_decision_hashes:
        return False
    
    # Calculate turnover
    turnover = compute_turnover(old_weights, new_weights)
    
    # Gate: Must have meaningful turnover OR high-impact news
    if turnover >= min_turnover or high_impact_news:
        # Mark this decision as logged to prevent rerun spam
        st.session_state.logged_decision_hashes.add(decision_hash)
        # Limit set size to prevent memory growth (keep last 100)
        if len(st.session_state.logged_decision_hashes) > 100:
            st.session_state.logged_decision_hashes = set(
                list(st.session_state.logged_decision_hashes)[-100:]
            )
        return True
    
    return False


def format_decision_message(
    action_type: str,
    portfolio_name: str,
    old_weights: dict,
    new_weights: dict,
    relevant_headlines: list,
    regime: str
) -> str:
    """
    Create a rich, informative decision log message.
    Includes top changes and relevant headlines.
    """
    turnover = compute_turnover(old_weights, new_weights)
    top_changes = get_top_changes(old_weights, new_weights, top_n=3)
    
    message_parts = [
        f"{action_type} in {portfolio_name}",
        f"(Turnover: {turnover*100:.1f}%)",
    ]
    
    # Add top changes with old→new weights
    if top_changes:
        changes_text = " | ".join([
            f"{ticker}: {old_w*100:.1f}%→{new_w*100:.1f}% ({delta*100:+.1f}%)"
            for ticker, old_w, new_w, delta in top_changes
        ])
        message_parts.append(f"Changes: {changes_text}")
    
    # Add relevant headlines (if any)
    if relevant_headlines:
        headlines_text = " | ".join([
            f"'{h['title'][:50]}...' ({h['source']}, {h['label']}, impact {h['impact_score']:.2f})"
            for h in relevant_headlines
        ])
        message_parts.append(f"Drivers: {headlines_text}")
    
    return " — ".join(message_parts)


# ----------------------------
# UI Styling (dark mobile vibe)
# ----------------------------
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




def pill(text: str) -> str:
    return f'<span class="cm-pill">{text}</span>'




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




# ---------------------------------------
# Manual Reallocation (safe + explainable)
# ---------------------------------------
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




def sentiment_class(label: str) -> str:
    label_l = (label or "").lower()
    if "positive" in label_l:
        return "sent-pos"
    if "negative" in label_l:
        return "sent-neg"
    return "sent-neu"




def default_index(options: list, preferred: str) -> int:
    try:
        return options.index(preferred)
    except ValueError:
        return 0




# -------------
# Main app
# -------------
def main() -> None:
    st.set_page_config(page_title="News-Driven Portfolio Simulator", layout="wide")
    apply_dark_vibes_css()
    st_autorefresh(interval=int(REFRESH_SECONDS * 1000), key="auto_refresh")
    db.init_db()


    # Initialize session state
    if "bull_weights" not in st.session_state:
        st.session_state.bull_weights = {}
    if "bear_weights" not in st.session_state:
        st.session_state.bear_weights = {}
    if "show_sentiment_modal" not in st.session_state:
        st.session_state.show_sentiment_modal = False
    if "pending_analysis" not in st.session_state:
        st.session_state.pending_analysis = None
    if "reallocate_approved" not in st.session_state:
        st.session_state.reallocate_approved = False
    # Track previous weights to detect real changes (not just reruns)
    if "prev_bull_weights" not in st.session_state:
        st.session_state.prev_bull_weights = {}
    if "prev_bear_weights" not in st.session_state:
        st.session_state.prev_bear_weights = {}


    now = utc_now_iso()


    st.title("News-Driven Portfolio Simulator")
    st.caption("Simulation-only: RSS news → sentiment/impact → explainable allocation rules. No real trading.")


    # --- Fetch headlines ---
    headlines = fetch_rss_headlines(RSS_FEEDS, limit_total=18)
    if not headlines:
        headlines = [
            {"title": "Markets mixed as investors await inflation data", "source": "Fallback", "published": ""},
            {"title": "Tech stocks rise after strong earnings guidance", "source": "Fallback", "published": ""},
            {"title": "Oil climbs on geopolitical tensions", "source": "Fallback", "published": ""},
        ]


    # --- Analyze headlines + store ---
    analyses = []
    for h in headlines:
        title = clean_text(h.get("title", ""))
        source = clean_text(h.get("source", ""))
        published = clean_text(h.get("published", ""))
        news_id = db.insert_news(fetched_at=now, title=title, source=source, published=published)


        a = analyze_headline(title)
        if a.label in ("Positive", "Negative") and a.impact_score >= 0.40 and not st.session_state.show_sentiment_modal:
            st.session_state.show_sentiment_modal = True
            st.session_state.pending_analysis = {
                "title": title,
                "label": a.label,
                "impact_label": a.impact_label,
                "impact_score": a.impact_score,
                "category": a.category,
            }


        db.insert_sentiment(
            news_id=news_id,
            analyzed_at=now,
            label=a.label,
            compound=a.compound,
            impact_label=a.impact_label,
            impact_score=a.impact_score,
            category=a.category,
        )


        analyses.append({
            "title": title,
            "source": source,
            "published": published,
            "label": a.label,
            "compound": a.compound,
            "impact_label": a.impact_label,
            "impact_score": a.impact_score,
            "category": a.category,
        })


    # --- Determine regime ---
    regime, reason = determine_regime(analyses)
    
    # Only log regime decision once per unique regime+reason combination
    # This prevents logging the same regime on every refresh
    regime_hash = create_decision_hash(regime, {}, now)
    relevant_headlines = get_relevant_headlines(analyses, top_n=2)
    has_high_impact = len(relevant_headlines) > 0
    
    # Gate: Only log if this is a new regime decision (not a rerun)
    if should_log_decision({}, {}, regime_hash, min_turnover=0.0, high_impact_news=has_high_impact):
        # Format message with relevant headlines if available
        if relevant_headlines:
            headlines_text = " | ".join([
                f"'{h['title'][:50]}...' ({h['source']}, {h['label']}, impact {h['impact_score']:.2f})"
                for h in relevant_headlines
            ])
            enhanced_reason = f"{reason} — Drivers: {headlines_text}"
        else:
            enhanced_reason = reason
        db.log_decision(now, regime, enhanced_reason)


    # --- Sentiment approval (using expander instead of modal) ---
    if st.session_state.show_sentiment_modal:
        a = st.session_state.pending_analysis
        with st.expander("📢 Market Sentiment Alert (Click to review)", expanded=True):
            st.markdown(f"""
            **Headline:** {a['title']}
           
            **Sentiment:** `{a['label']}` 
            **Impact:** `{a['impact_label']}` ({a['impact_score']:.2f}) 
            **Category:** `{a['category']}`


            ---
            Would you like to **reallocate assets based on this sentiment?**
            """)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Yes, Allow Reallocation", key="yes_reallocate"):
                    st.session_state.reallocate_approved = True
                    st.session_state.show_sentiment_modal = False
            with col2:
                if st.button("❌ No, Ignore", key="no_reallocate"):
                    st.session_state.reallocate_approved = False
                    st.session_state.show_sentiment_modal = False


    # --- Base portfolios ---
    base_bull, base_bear = build_portfolios(
        bullish_universe=BULLISH_UNIVERSE,
        bearish_universe=BEARISH_UNIVERSE,
        regime=regime,
        prev_bull=st.session_state.bull_weights,
        prev_bear=st.session_state.bear_weights,
    )
    
    # Initialize portfolios if empty
    if not st.session_state.bull_weights:
        st.session_state.bull_weights = base_bull
        st.session_state.prev_bull_weights = base_bull
    if not st.session_state.bear_weights:
        st.session_state.bear_weights = base_bear
        st.session_state.prev_bear_weights = base_bear


    # --- Prices ---
    all_tickers = sorted(set(BULLISH_UNIVERSE + BEARISH_UNIVERSE))
    prices = fetch_latest_prices(all_tickers)


    # --- Status bar ---
    st.markdown(f"""
    <div class="cm-card">
        {pill("Simulation Only")}
        {pill(f"Refresh: {REFRESH_SECONDS}s")}
        {pill(f"Regime: {regime}")}
        {pill(f"UTC: {now}")}
        <div style="margin-top:6px; opacity:0.9;">
            <b>Decision:</b> {reason}
        </div>
    </div>
    """, unsafe_allow_html=True)


    # --- Layout ---
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
        # --- Reallocation panel ---
        st.markdown('<div class="mobile-wrap">', unsafe_allow_html=True)
        st.markdown('<div class="cm-card">', unsafe_allow_html=True)


        if not st.session_state.reallocate_approved:
            st.info("Waiting for sentiment-trigger approval from news alert.")
        else:
            st.success("Sentiment-approved reallocation enabled.")


        st.markdown('<p class="cm-title">Reallocate Asset Based on Sentiment</p>', unsafe_allow_html=True)
        st.markdown('<p class="cm-sub">Adjust a simulated portfolio weight and confirm.</p>', unsafe_allow_html=True)


        # --- Portfolio selection ---
        portfolio_options = ["Bullish (Risk-On)", "Bearish (Risk-Reduced)"]
        default_portfolio = "Bullish (Risk-On)"
        portfolio_choice = st.selectbox(
            "Portfolio",
            portfolio_options,
            index=default_index(portfolio_options, default_portfolio),
        )


        if portfolio_choice.startswith("Bullish"):
            active_key = "bull_weights"
            prev_key = "prev_bull_weights"
            universe = BULLISH_UNIVERSE
        else:
            active_key = "bear_weights"
            prev_key = "prev_bear_weights"
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


        st.markdown(f"""
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
        """, unsafe_allow_html=True)


        st.markdown("---")
        st.caption("Adjust weight (other holdings scale automatically to keep total at 100%).")
        max_slider = min(0.20, float(MAX_WEIGHT_PER_STOCK))
        target_w = st.slider(
            f"{ticker} target weight",
            min_value=0.0,
            max_value=float(max_slider),
            value=float(min(current_w, max_slider)),
            step=0.005,
            format="%.3f",
        )


        st.write(f"Target: **{target_w*100:.1f}%**  (From **{current_w*100:.1f}%**)")


        confirm = st.button("CONFIRM REALLOCATION", type="primary")
        if confirm:
            # Store old weights before updating
            old_weights = dict(st.session_state[active_key])
            
            # Apply rebalance
            updated = rebalance_to_target(active_weights, ticker, target_w)
            st.session_state[active_key] = updated
            
            # Save snapshot
            db.save_portfolio_snapshot(now, regime, f"{portfolio_choice}_MANUAL", updated)
            
            # Create decision hash for deduplication
            decision_hash = create_decision_hash(regime, updated, now)
            
            # Get relevant high-impact headlines
            relevant_headlines = get_relevant_headlines(analyses, top_n=2)
            has_high_impact = len(relevant_headlines) > 0
            
            # Gate: Only log if meaningful change (turnover >= 1% OR high-impact news)
            # This prevents logging tiny slider movements or rerun spam
            if should_log_decision(old_weights, updated, decision_hash, min_turnover=0.01, high_impact_news=has_high_impact):
                # Format rich message with changes and drivers
                message = format_decision_message(
                    action_type="Manual reallocation",
                    portfolio_name=portfolio_choice,
                    old_weights=old_weights,
                    new_weights=updated,
                    relevant_headlines=relevant_headlines,
                    regime=regime
                )
                db.log_decision(now, regime, message)
                st.success("Reallocation applied and logged (simulation).")
            else:
                # Change was too small or duplicate
                st.success("Reallocation applied (simulation). Change too small to log.")
            
            # Update previous weights tracker
            st.session_state[prev_key] = updated


        st.markdown(
            "<div style='opacity:0.75; font-size:12px; margin-top:10px;'>"
            "All outputs are simulation-only and for research/educational use."
            "</div>", unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)  # end card
        st.markdown("</div>", unsafe_allow_html=True)  # end mobile-wrap


        st.subheader("Portfolio Weights")
        tab1, tab2 = st.tabs(["Bullish", "Bearish"])
        with tab1:
            st.dataframe(weights_to_rows(st.session_state.bull_weights, prices), use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(weights_to_rows(st.session_state.bear_weights, prices), use_container_width=True, hide_index=True)


        st.caption("Weights are capped. Prices are delayed/approx for display only.")


    st.divider()
    st.subheader("Decision Log")
    for d in db.get_recent_decisions(limit=10):
        st.markdown(f"- `{d['created_at']}` **{d['regime']}** — {d['message']}")




if __name__ == "__main__":
    main()