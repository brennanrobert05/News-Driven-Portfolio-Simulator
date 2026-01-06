import feedparser

#Headline web-scraper
def fetch_rss_headlines(feeds, limit_total=20):
    items = []
    seen = set()

    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            source = parsed.feed.get("title", url)

            per_feed = max(5, limit_total // max(1, len(feeds)))
            for entry in parsed.entries[:per_feed]:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue

                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)

                published = entry.get("published") or entry.get("updated") or ""
                items.append({"title": title, "source": source, "published": published})

        except Exception:
            # If one feed fails, skip it and continue
            continue

    return items[:limit_total]