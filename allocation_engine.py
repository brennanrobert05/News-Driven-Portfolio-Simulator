# allocation_engine.py
# Option A rule-guided allocation:
# - determine a regime from aggregated news sentiment/impact
# - generate capped, turnover-limited allocations for each universe

from config import MAX_WEIGHT_PER_STOCK, MAX_TURNOVER_PER_UPDATE

def equal_weight(tickers):
    if not tickers:
        return {}
    w = 1.0 / len(tickers)
    return {t: w for t in tickers}

def clamp_weights(weights):
    # cap each weight, then renormalize
    capped = {k: min(MAX_WEIGHT_PER_STOCK, max(0.0, float(v))) for k, v in weights.items()}
    s = sum(capped.values())
    if s <= 0:
        return capped
    return {k: v / s for k, v in capped.items()}

def limit_turnover(prev, target):
    # limits total absolute change per update
    all_keys = set(prev) | set(target)
    diffs = {k: target.get(k, 0.0) - prev.get(k, 0.0) for k in all_keys}
    turnover = sum(abs(d) for d in diffs.values())

    if turnover <= MAX_TURNOVER_PER_UPDATE or turnover == 0:
        return target

    scale = MAX_TURNOVER_PER_UPDATE / turnover
    limited = {k: prev.get(k, 0.0) + diffs[k] * scale for k in all_keys}
    limited = {k: max(0.0, v) for k, v in limited.items()}
    s = sum(limited.values())
    if s <= 0:
        return target
    return {k: v / s for k, v in limited.items()}

def determine_regime(analyses):
    """
    analyses: list of dicts with keys label, impact_score, category
    returns: (regime, reason)
    """
    if not analyses:
        return "Neutral", "No news signals available; defaulting to Neutral."

    pos = 0.0
    neg = 0.0
    macro_geo_neg = 0.0

    for a in analyses:
        label = a.get("label")
        impact = float(a.get("impact_score") or 0.0)
        cat = a.get("category") or "Mixed"

        if label == "Positive":
            pos += impact
        elif label == "Negative":
            neg += impact
            if cat in ("Macro", "Geopolitical", "Mixed"):
                macro_geo_neg += impact

    # Risk-off trigger: strong negative macro/geopolitical dominates
    if macro_geo_neg >= 1.0 and neg > pos:
        return "Bearish", "Risk-off: negative macro/geopolitical signals dominate."

    # Risk-on trigger: strong positive dominates
    if pos >= 1.0 and pos > neg:
        return "Bullish", "Risk-on: positive news signals dominate."

    return "Neutral", "Mixed signals: holding Neutral regime."

def build_portfolios(bullish_universe, bearish_universe, regime, prev_bull, prev_bear):
    bull_target = equal_weight(bullish_universe)
    bear_target = equal_weight(bearish_universe)

    # small explainable regime tilts
    if regime == "Bullish":
        for t in ["NVDA", "MSFT", "AAPL", "AMZN"]:
            if t in bull_target:
                bull_target[t] += 0.01
    elif regime == "Bearish":
        for t in ["BRK-B", "JNJ", "PG", "WMT"]:
            if t in bear_target:
                bear_target[t] += 0.01

    bull_target = clamp_weights(bull_target)
    bear_target = clamp_weights(bear_target)

    bull_final = limit_turnover(prev_bull or bull_target, bull_target)
    bear_final = limit_turnover(prev_bear or bear_target, bear_target)

    return bull_final, bear_final
