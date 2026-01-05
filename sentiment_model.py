# sentiment_model.py
# Option A (explainable):
# - Sentiment: VADER compound + small transparent finance keyword nudges
# - Impact strength: keyword-based macro/geopolitical/company boosts

from dataclasses import dataclass
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

ANALYZER = SentimentIntensityAnalyzer()

POS_FINANCE = {
    "beats", "beat", "surge", "soar", "record", "upgrade", "raises guidance",
    "strong demand", "profit jumps", "rally", "growth accelerates",
}
NEG_FINANCE = {
    "miss", "misses", "plunge", "drop", "falls", "downgrade", "cuts guidance",
    "lawsuit", "probe", "sec", "fine", "fraud", "recall", "bankruptcy", "layoffs",
}

MACRO_KEYS = {"inflation", "cpi", "rate", "rates", "fed", "ecb", "boe", "recession", "gdp", "unemployment", "yield"}
GEO_KEYS = {"war", "conflict", "sanction", "election", "attack", "tariff", "trade ban", "border"}
COMPANY_KEYS = {"earnings", "guidance", "revenue", "profit", "ceo", "ipo", "merger", "acquisition", "buyback"}

@dataclass
class HeadlineAnalysis:
    label: str          # Positive / Neutral / Negative
    compound: float     # -1..+1
    impact_label: str   # Low / Medium / High
    impact_score: float # 0..1
    category: str       # Macro / Geopolitical / Company / Mixed

def analyze_headline(headline: str) -> HeadlineAnalysis:
    text = headline or ""
    t = text.lower()

    base = ANALYZER.polarity_scores(text)["compound"]

    # Transparent finance-language nudges
    if any(k in t for k in POS_FINANCE):
        base += 0.10
    if any(k in t for k in NEG_FINANCE):
        base -= 0.10

    base = max(-1.0, min(1.0, base))

    if base >= 0.15:
        label = "Positive"
    elif base <= -0.15:
        label = "Negative"
    else:
        label = "Neutral"

    macro = any(k in t for k in MACRO_KEYS)
    geo = any(k in t for k in GEO_KEYS)
    comp = any(k in t for k in COMPANY_KEYS)

    if macro and not (geo or comp):
        category = "Macro"
    elif geo and not (macro or comp):
        category = "Geopolitical"
    elif comp and not (macro or geo):
        category = "Company"
    else:
        category = "Mixed"

    # Impact: absolute sentiment + keyword boosts
    impact = min(1.0, abs(base) * 0.7)
    if macro:
        impact += 0.20
    if geo:
        impact += 0.20
    if comp:
        impact += 0.15
    impact = max(0.0, min(1.0, impact))

    if impact >= 0.70:
        impact_label = "High"
    elif impact >= 0.40:
        impact_label = "Medium"
    else:
        impact_label = "Low"

    return HeadlineAnalysis(
        label=label,
        compound=float(base),
        impact_label=impact_label,
        impact_score=float(impact),
        category=category,
    )