#!/usr/bin/env python3
"""
Reddit Buzz Score Scraper for MLB Prospects
============================================

Tracks prospect mentions across fantasy baseball subreddits and (optionally)
news articles via GNews API. Calculates a "Buzz Score" (0-100) from Reddit.

Setup:
1. Install: pip install -r requirements.txt  (praw, python-dotenv, requests)
2. Reddit app at https://www.reddit.com/prefs/apps (script, redirect http://localhost:8080)
3. Optional: GNews API key at https://gnews.io/register for news scraping
4. Create .env with credentials (see EXAMPLE_ENV in code)
5. Run: python reddit-buzz-scraper.py

Author: Rankle System
"""

import praw
import json
import math
import time
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

try:
    import requests
except ImportError:
    requests = None  # type: ignore

# ============================================================================
# CONFIGURATION
# ============================================================================

EXAMPLE_ENV = """
# Copy this to .env and fill in your credentials
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=ProspectBuzzTracker/1.0 by YourUsername

# Optional: GNews API for news article scraping (get key at https://gnews.io/register)
# GNEWS_API_KEY=your_gnews_api_key_here
"""

# Target subreddits with weights
SUBREDDITS = {
    "fantasybaseball": 1.5,
    "MLBProspects": 1.3,
    "MinorLeagueBaseball": 1.2,
    "baseball": 1.0,
}

# Sentiment keywords
POSITIVE_KEYWORDS = [
    "breakout", "sleeper", "stash", "must-add", "must add", "call-up", "callup",
    "promoted", "raking", "mashing", "filthy", "ace", "stud", "league winner",
    "add now", "get him", "fire", "elite", "dominant", "nasty", "underrated"
]

NEGATIVE_KEYWORDS = [
    "injured", "injury", "IL", "surgery", "torn", "struggling", "demoted",
    "bust", "avoid", "drop", "overrated", "overhyped", "disappointing",
    "setback", "shut down", "out for", "DL"
]

# Algorithm parameters
DECAY_LAMBDA = 0.1  # Half-life ~7 days
DAYS_TO_TRACK = 30
MAX_SINGLE_POST_CONTRIBUTION = 0.25  # Cap at 25% of total

# Rate limiting
REQUESTS_PER_MINUTE = 60
REQUEST_DELAY = 1.0  # seconds between requests (safe margin)

# News API (GNews) - optional
GNEWS_BASE_URL = "https://gnews.io/api/v4/search"
GNEWS_MAX_ARTICLES = 10
GNEWS_REQUEST_DELAY = 0.5  # seconds between requests (free tier)

# News scoring (same recency decay as Reddit; sentiment affects sign/magnitude)
NEWS_BASE_POINTS = 8
NEWS_SENTIMENT_POSITIVE = 1.2   # positive news adds to score
NEWS_SENTIMENT_NEGATIVE = -1.0  # negative news hurts score
NEWS_SENTIMENT_NEUTRAL = 0.3    # neutral news slight positive
MAX_SINGLE_NEWS_CONTRIBUTION = 0.25  # cap single article impact


def analyze_sentiment(text: str) -> str:
    """Shared keyword-based sentiment for Reddit and news (positive/negative/neutral)."""
    if not text:
        return "neutral"
    text_lower = text.lower()
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)
    if neg_count > pos_count:
        return "negative"
    if pos_count > neg_count:
        return "positive"
    return "neutral"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class NewsArticle:
    """A news article mentioning a prospect"""
    title: str
    url: str
    source: str
    published_at: str   # display string (e.g. "Jan 15")
    published_ts: int   # Unix timestamp for recency decay
    description: str
    sentiment: str = "neutral"   # positive / negative / neutral
    contribution: float = 0.0   # computed buzz contribution (can be negative)


@dataclass
class Mention:
    """A single mention of a prospect on Reddit"""
    id: str
    subreddit: str
    type: str  # "title", "body", or "comment"
    title: str
    text: str
    score: int
    num_comments: int
    created_utc: int
    url: str
    sentiment: str  # "positive", "negative", "neutral"
    confidence: float
    contribution: float = 0.0  # Calculated buzz contribution


@dataclass 
class Prospect:
    """A prospect being tracked"""
    id: str
    first_name: str
    last_name: str
    team: str
    position: str = ""
    aliases: list = field(default_factory=list)  # Alternative names/nicknames


@dataclass
class BuzzResult:
    """Buzz score calculation result for a prospect"""
    prospect_id: str
    name: str
    team: str
    buzz_score: float
    raw_buzz: float
    mention_count_7d: int
    mention_count_30d: int
    days_with_mentions: int
    negative_ratio: float
    mentions: list
    news_articles: list = field(default_factory=list)
    last_updated: str = ""  # set in calculate_buzz_result


# ============================================================================
# NEWS SCRAPER (GNews API)
# ============================================================================

class NewsScraper:
    """Fetches news articles about prospects via GNews API"""

    def __init__(self, api_key: str):
        if not requests:
            raise RuntimeError("Install requests: pip install requests")
        self.api_key = api_key
        self.session = requests.Session()

    def search_prospect(self, prospect: Prospect) -> list[NewsArticle]:
        """Search for recent news articles about a prospect"""
        query = f'"{prospect.first_name} {prospect.last_name}" MLB'
        params = {
            "q": query,
            "lang": "en",
            "max": GNEWS_MAX_ARTICLES,
            "apikey": self.api_key,
        }
        try:
            time.sleep(GNEWS_REQUEST_DELAY)
            resp = self.session.get(GNEWS_BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"    News API error for {prospect.last_name}: {e}")
            return []

        articles = []
        raw_published = None
        for item in data.get("articles", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue
            # Basic relevance: prospect name in title or description
            full_name = f"{prospect.first_name} {prospect.last_name}".lower()
            desc = (item.get("description") or item.get("content") or "")[:200].strip()
            content = (desc + " " + title).lower()
            if full_name not in content and prospect.last_name.lower() not in content:
                continue
            raw_published = item.get("publishedAt") or ""
            published_ts = 0
            published_at = ""
            if raw_published and len(raw_published) >= 10:
                try:
                    dt = datetime.fromisoformat(raw_published.replace("Z", "+00:00"))
                    published_ts = int(dt.timestamp())
                    published_at = dt.strftime("%b %d")
                except Exception:
                    published_at = raw_published[:10] if len(raw_published) >= 10 else ""
            text_for_sentiment = title + " " + desc
            sentiment = analyze_sentiment(text_for_sentiment)
            articles.append(
                NewsArticle(
                    title=title,
                    url=item.get("url") or "",
                    source=(item.get("source") or {}).get("name", "Unknown"),
                    published_at=published_at,
                    published_ts=published_ts,
                    description=desc,
                    sentiment=sentiment,
                )
            )
        return articles


# ============================================================================
# REDDIT CLIENT
# ============================================================================

class RedditBuzzScraper:
    """Scrapes Reddit for prospect mentions and calculates buzz scores"""
    
    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        """Initialize Reddit API connection"""
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self.request_count = 0
        self.last_request_time = 0
        
    def _rate_limit(self):
        """Enforce rate limiting"""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self.last_request_time = time.time()
        self.request_count += 1
        
        if self.request_count % 10 == 0:
            print(f"  [{self.request_count} requests made]")
    
    def search_prospect(self, prospect: Prospect, limit_per_sub: int = 100) -> list[Mention]:
        """Search for all mentions of a prospect across target subreddits"""
        mentions = []
        search_terms = self._build_search_terms(prospect)
        
        for subreddit_name, weight in SUBREDDITS.items():
            print(f"  Searching r/{subreddit_name}...")
            
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                
                for term in search_terms:
                    self._rate_limit()
                    
                    # Search posts
                    try:
                        for post in subreddit.search(term, time_filter="month", limit=limit_per_sub):
                            mention = self._process_post(post, prospect, subreddit_name)
                            if mention:
                                mentions.append(mention)
                    except Exception as e:
                        print(f"    Warning: Search error for '{term}': {e}")
                        continue
                        
            except Exception as e:
                print(f"    Error accessing r/{subreddit_name}: {e}")
                continue
        
        # Deduplicate by ID
        seen_ids = set()
        unique_mentions = []
        for m in mentions:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                unique_mentions.append(m)
        
        return unique_mentions
    
    def _build_search_terms(self, prospect: Prospect) -> list[str]:
        """Build search terms for a prospect"""
        terms = [
            f'"{prospect.first_name} {prospect.last_name}"',  # Full name exact
        ]
        # Add aliases
        for alias in prospect.aliases:
            terms.append(f'"{alias}"')
        return terms
    
    def _process_post(self, post, prospect: Prospect, subreddit: str) -> Optional[Mention]:
        """Process a Reddit post and extract mention data"""
        # Check if prospect is actually mentioned
        full_name = f"{prospect.first_name} {prospect.last_name}".lower()
        title_lower = post.title.lower()
        body_lower = (post.selftext or "").lower()
        
        # Determine mention type and confidence
        mention_type = None
        confidence = 0.0
        
        if full_name in title_lower:
            mention_type = "title"
            confidence = 1.0
        elif full_name in body_lower:
            mention_type = "body"
            confidence = 1.0
        elif prospect.last_name.lower() in title_lower or prospect.last_name.lower() in body_lower:
            # Last name only - check for context
            text_combined = title_lower + " " + body_lower
            context_clues = [prospect.team.lower(), "prospect", prospect.position.lower(), "minors", "minor league"]
            if any(clue in text_combined for clue in context_clues if clue):
                mention_type = "title" if prospect.last_name.lower() in title_lower else "body"
                confidence = 0.8
        
        if not mention_type or confidence == 0:
            return None
        
        # Analyze sentiment (shared with news)
        text_combined = post.title + " " + (post.selftext or "")
        sentiment = analyze_sentiment(text_combined)
        
        return Mention(
            id=post.id,
            subreddit=subreddit,
            type=mention_type,
            title=post.title,
            text=(post.selftext or "")[:500],  # Truncate for storage
            score=post.score,
            num_comments=post.num_comments,
            created_utc=int(post.created_utc),
            url=f"https://reddit.com{post.permalink}",
            sentiment=sentiment,
            confidence=confidence,
        )
    
# ============================================================================
# BUZZ SCORE CALCULATOR
# ============================================================================

class BuzzCalculator:
    """Calculates buzz scores from mentions"""
    
    def __init__(self):
        self.all_raw_scores = []  # For normalization across prospects
    
    def calculate_raw_buzz(self, mentions: list[Mention]) -> float:
        """Calculate raw buzz score from mentions"""
        now = datetime.now(timezone.utc)
        total = 0.0
        
        for mention in mentions:
            # Base points by mention type
            base_points = {"title": 10, "body": 5, "comment": 2}.get(mention.type, 2)
            
            # Engagement multiplier (logarithmic)
            engagement = 1 + math.log10(1 + mention.score)
            if mention.num_comments > 0:
                engagement += 0.5 * math.log10(1 + mention.num_comments)
            
            # Subreddit weight
            sub_weight = SUBREDDITS.get(mention.subreddit, 1.0)
            
            # Recency decay
            mention_time = datetime.fromtimestamp(mention.created_utc, tz=timezone.utc)
            days_old = (now - mention_time).days
            decay = math.exp(-DECAY_LAMBDA * days_old)
            
            # Sentiment modifier
            sentiment_mod = {"positive": 1.2, "negative": 0.7, "neutral": 1.0}.get(mention.sentiment, 1.0)
            
            # Calculate contribution
            contribution = base_points * engagement * sub_weight * decay * sentiment_mod * mention.confidence
            mention.contribution = contribution
            total += contribution
        
        return total

    def calculate_news_contribution(self, news_articles: list) -> float:
        """Calculate buzz contribution from news: positive adds, negative hurts, weighted by recency."""
        now = datetime.now(timezone.utc)
        cutoff_30d = now.timestamp() - (30 * 24 * 3600)
        sentiment_mod = {
            "positive": NEWS_SENTIMENT_POSITIVE,
            "negative": NEWS_SENTIMENT_NEGATIVE,
            "neutral": NEWS_SENTIMENT_NEUTRAL,
        }
        total = 0.0
        for article in news_articles:
            if getattr(article, "published_ts", 0) < cutoff_30d:
                continue
            days_old = (now.timestamp() - article.published_ts) / (24 * 3600)
            decay = math.exp(-DECAY_LAMBDA * days_old)
            mod = sentiment_mod.get(article.sentiment, NEWS_SENTIMENT_NEUTRAL)
            contribution = NEWS_BASE_POINTS * decay * mod
            article.contribution = contribution
            total += contribution
        # Cap single article impact (no one piece > 25% of |total|)
        if news_articles and total != 0:
            abs_total = abs(total)
            for article in news_articles:
                if getattr(article, "published_ts", 0) < cutoff_30d:
                    continue
                cap = abs_total * MAX_SINGLE_NEWS_CONTRIBUTION
                if abs(article.contribution) > cap:
                    excess = abs(article.contribution) - cap
                    if article.contribution < 0:
                        total += excess
                    else:
                        total -= excess
                    article.contribution = cap if article.contribution > 0 else -cap
        return total

    def normalize_score(self, raw_buzz: float, all_scores: list[float]) -> float:
        """Normalize raw buzz to 0-100 scale using percentiles"""
        if not all_scores or len(all_scores) < 2:
            # Fallback: simple scaling
            return min(100, max(0, raw_buzz))
        
        sorted_scores = sorted(all_scores)
        p5_idx = max(0, int(len(sorted_scores) * 0.05))
        p95_idx = min(len(sorted_scores) - 1, int(len(sorted_scores) * 0.95))
        
        p5 = sorted_scores[p5_idx]
        p95 = sorted_scores[p95_idx]
        
        if p95 == p5:
            return 50.0  # All scores are the same
        
        normalized = ((raw_buzz - p5) / (p95 - p5)) * 100
        return min(100, max(0, normalized))
    
    def calculate_buzz_result(
        self,
        prospect: Prospect,
        mentions: list[Mention],
        all_scores: list[float] = None,
        news_articles: list = None,
    ) -> BuzzResult:
        """Calculate complete buzz result for a prospect"""
        now = datetime.now(timezone.utc)
        if news_articles is None:
            news_articles = []

        # Filter to past 30 days
        cutoff_30d = now.timestamp() - (30 * 24 * 3600)
        cutoff_7d = now.timestamp() - (7 * 24 * 3600)

        mentions_30d = [m for m in mentions if m.created_utc >= cutoff_30d]
        mentions_7d = [m for m in mentions if m.created_utc >= cutoff_7d]

        # Reddit raw buzz
        raw_buzz_reddit = self.calculate_raw_buzz(mentions_30d)
        if mentions_30d:
            max_contribution = max(m.contribution for m in mentions_30d)
            if max_contribution > raw_buzz_reddit * MAX_SINGLE_POST_CONTRIBUTION:
                excess = max_contribution - (raw_buzz_reddit * MAX_SINGLE_POST_CONTRIBUTION)
                raw_buzz_reddit -= excess

        # News contribution (positive adds, negative hurts; recency-weighted)
        raw_buzz_news = self.calculate_news_contribution(news_articles)
        raw_buzz = raw_buzz_reddit + raw_buzz_news

        # Normalize
        if all_scores:
            buzz_score = self.normalize_score(raw_buzz, all_scores)
        else:
            # Simple scaling if no comparison data
            buzz_score = min(100, raw_buzz / 2)  # Rough heuristic

        # Calculate additional metrics
        unique_days = len(set(
            datetime.fromtimestamp(m.created_utc, tz=timezone.utc).date()
            for m in mentions_30d
        ))

        negative_count = sum(1 for m in mentions_30d if m.sentiment == "negative")
        negative_ratio = negative_count / len(mentions_30d) if mentions_30d else 0

        return BuzzResult(
            prospect_id=prospect.id,
            name=f"{prospect.first_name} {prospect.last_name}",
            team=prospect.team,
            buzz_score=round(buzz_score, 1),
            raw_buzz=round(raw_buzz, 2),
            mention_count_7d=len(mentions_7d),
            mention_count_30d=len(mentions_30d),
            days_with_mentions=unique_days,
            negative_ratio=round(negative_ratio, 2),
            mentions=[asdict(m) for m in mentions_30d],
            news_articles=[asdict(a) for a in news_articles],
            last_updated=now.isoformat(),
        )


# ============================================================================
# MAIN FUNCTIONS
# ============================================================================

def load_prospects(filepath: str) -> list[Prospect]:
    """Load prospect list from JSON file"""
    if not os.path.exists(filepath):
        # Return sample prospects for testing
        return [
            Prospect("jackson-holliday", "Jackson", "Holliday", "BAL", "SS"),
            Prospect("paul-skenes", "Paul", "Skenes", "PIT", "SP"),
            Prospect("wyatt-langford", "Wyatt", "Langford", "TEX", "OF"),
            Prospect("colton-cowser", "Colton", "Cowser", "BAL", "OF"),
            Prospect("ceddanne-rafaela", "Ceddanne", "Rafaela", "BOS", "SS"),
        ]
    
    with open(filepath, "r") as f:
        data = json.load(f)
        return [Prospect(**p) for p in data]


def save_results(results: list[BuzzResult], filepath: str):
    """Save buzz results to JSON file"""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prospect_count": len(results),
        "results": [asdict(r) for r in results],
    }
    
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to {filepath}")


def load_env():
    """Load environment variables from .env file"""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


def main():
    """Main entry point"""
    print("=" * 60)
    print("Prospect Buzz Score Scraper (Reddit + News)")
    print("=" * 60)

    # Load environment
    load_env()

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "ProspectBuzzTracker/1.0")
    gnews_key = os.environ.get("GNEWS_API_KEY", "").strip()

    # At least one source required (Reddit or GNews)
    reddit_ok = bool(client_id and client_secret)
    news_ok = bool(gnews_key and requests)
    if not reddit_ok and not news_ok:
        print("\nERROR: No API credentials found. You need at least one:")
        print("  • Reddit: REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in .env")
        print("  • News:   GNEWS_API_KEY in .env (get key at https://gnews.io/register)")
        if not requests:
            print("  (Install requests: pip install requests)")
        print("\nExample .env for news-only mode:")
        print("  GNEWS_API_KEY=your_key_here")
        return

    # Initialize scrapers
    scraper = None
    if reddit_ok:
        print("\nReddit: enabled")
        scraper = RedditBuzzScraper(client_id, client_secret, user_agent)
    else:
        print("\nReddit: skipped (no credentials — news-only mode)")

    if news_ok:
        print("News:   enabled (GNews API)")
        news_scraper = NewsScraper(gnews_key)
    else:
        news_scraper = None
        if not gnews_key:
            print("News:   skipped (set GNEWS_API_KEY in .env to enable)")

    calculator = BuzzCalculator()

    # Load prospects
    prospects_file = Path(__file__).parent / "prospects.json"
    prospects = load_prospects(str(prospects_file))
    print(f"\nLoaded {len(prospects)} prospects to track")

    # Scrape Reddit (if enabled) + news (if enabled) for each prospect
    all_results = []
    all_raw_scores = []

    for i, prospect in enumerate(prospects, 1):
        print(f"\n[{i}/{len(prospects)}] Scanning for {prospect.first_name} {prospect.last_name} ({prospect.team})...")

        mentions = scraper.search_prospect(prospect) if scraper else []
        if scraper:
            print(f"  Reddit: {len(mentions)} mentions")

        news_articles = []
        if news_scraper:
            news_articles = news_scraper.search_prospect(prospect)
            print(f"  News:   {len(news_articles)} articles")

        # Combined raw score (Reddit + news) for normalization
        raw_reddit = calculator.calculate_raw_buzz(mentions)
        raw_news = calculator.calculate_news_contribution(news_articles)
        all_raw_scores.append(raw_reddit + raw_news)

        # Store for later
        all_results.append((prospect, mentions, news_articles))

    # Now normalize and generate final results
    print("\n" + "=" * 60)
    print("BUZZ SCORE RESULTS")
    print("=" * 60)

    final_results = []
    for prospect, mentions, news_articles in all_results:
        result = calculator.calculate_buzz_result(
            prospect, mentions, all_raw_scores, news_articles=news_articles
        )
        final_results.append(result)

        # Print summary (buzz + news count)
        emoji = "🔥" if result.buzz_score >= 70 else "📈" if result.buzz_score >= 50 else "💬" if result.buzz_score >= 30 else "😴"
        news_part = f" | News: {len(result.news_articles)}" if result.news_articles else ""
        print(f"{emoji} {result.name:25} | Score: {result.buzz_score:5.1f} | 7d: {result.mention_count_7d:3} | 30d: {result.mention_count_30d:3}{news_part}")
        for art in result.news_articles[:2]:  # Top 2 headlines
            title = (art.get("title") or "").strip()
            if title:
                short = title[:52] + "..." if len(title) > 55 else title
                sent = art.get("sentiment", "neutral")
                print(f"      📰 {short} ({sent})")
    
    # Sort by buzz score
    final_results.sort(key=lambda x: x.buzz_score, reverse=True)
    
    # Save results
    output_file = Path(__file__).parent / "buzz_results.json"
    save_results(final_results, str(output_file))
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()