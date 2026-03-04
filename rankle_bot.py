import os
import json
import logging
import asyncio
import feedparser
import anthropic
import tweepy
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from hidden_gems import find_gems
from team_graphic import generate_team_graphic, TEAMS
from source_monitor import check_for_updates, get_status

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Clients
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
twitter = tweepy.Client(
    consumer_key=os.getenv("TWITTER_API_KEY"),
    consumer_secret=os.getenv("TWITTER_API_SECRET"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
)

CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

RANKLE_DESCRIPTION = (
    "Rankle (rankle.dev) is a baseball prospect ranking aggregator — "
    "like Rotten Tomatoes for prospects. It takes rankings from many sources "
    "and builds a consensus ranking by analyzing the distribution of each player's ranks."
)

RSS_FEEDS = [
    "https://www.baseballamerica.com/feed/",
    "https://www.fangraphs.com/feed/prospects/",
    "https://www.mlb.com/feeds/news/rss.xml",
    "https://www.baseballprospectus.com/feed/",
    "https://www.mlbtraderumors.com/feed/",
    "https://www.prospectslive.com/feed/",
    "https://www.reddit.com/r/baseball.rss",
    "https://www.reddit.com/r/fantasybaseball.rss",
]

SEEN_FILE = ".seen_articles.json"
PENDING_FILE = ".pending_tweets.json"

COLLEGE_KEYWORDS = [
    "college", "ncaa", "sec ", "acc ", "big ten", "big 12", "pac-12",
    "freshman", "sophomore", "junior", "draft eligible", "amateur",
    "high school", "prep "
]

MLB_KEYWORDS = [
    "free agent", "free-agent", "signing bonus", "contract extension",
    "designated hitter", "closer", "reliever", "rotation spot",
    "arbitration", "opt out", "trade deadline", "waiver",
]

MAX_DRAFTS_PER_CHECK = 10
RANKINGS_FILES = [
    "mlb-pipeline.json", "baseball-america.json", "fangraphs.json",
    "espn.json", "rotochamp.json", "rotoprospects.json",
    "prospect361.json", "bleacher-report.json", "just-baseball.json",
]


def load_top_prospects(top_n=20):
    """Load names of players ranked in the top N of any major list."""
    top = set()
    for filepath in RANKINGS_FILES:
        if os.path.exists(filepath):
            with open(filepath) as f:
                data = json.load(f)
                for player in data.get("list", []):
                    if player.get("rank", 999) <= top_n:
                        top.add(player["player_name"].lower())
    return top


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def load_pending():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE) as f:
            return json.load(f)
    return {}


def save_pending(pending):
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f)


def fetch_articles():
    seen = load_seen()
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                if entry.link not in seen:
                    articles.append({
                        "title": entry.title,
                        "summary": entry.get("summary", "")[:500],
                        "link": entry.link
                    })
        except Exception as e:
            logging.warning(f"Failed to fetch {url}: {e}")
    return articles, seen


def is_college_article(article):
    text = (article["title"] + " " + article["summary"]).lower()
    return any(kw in text for kw in COLLEGE_KEYWORDS)


def is_mlb_player_article(article):
    text = (article["title"] + " " + article["summary"]).lower()
    return any(kw in text for kw in MLB_KEYWORDS)


def filter_prospect_articles(articles):
    """Use Claude to batch-screen articles and return only prospect-relevant ones."""
    if not articles:
        return []
    titles = "\n".join([f"{i+1}. {a['title']}" for i, a in enumerate(articles)])
    prompt = (
        f"You are filtering baseball news articles for a prospect-focused audience.\n"
        f"Return ONLY the numbers of articles that are primarily about minor league prospects or prospect rankings.\n"
        f"Exclude anything about: active MLB players, free agents, established major leaguers, college players, coaching staff, signings of non-prospects, trades of established players, or general MLB news.\n"
        f"A prospect is someone in the minor leagues who has NOT yet established themselves at the MLB level.\n\n"
        f"Articles:\n{titles}\n\n"
        f"Reply with just the numbers, comma-separated. Example: 1, 3, 7"
    )
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    result = msg.content[0].text.strip()
    try:
        indices = [int(x.strip()) - 1 for x in result.split(",") if x.strip().isdigit()]
        return [articles[i] for i in indices if i < len(articles)]
    except Exception:
        return articles


def generate_news_tweet(article):
    prompt = (
        f"Generate a tweet about this baseball prospect news.\n\n"
        f"Title: {article['title']}\n"
        f"Summary: {article['summary']}\n\n"
        f"Your job is NOT to summarize the news — it's to find the most interesting, surprising, or underappreciated angle in it.\n\n"
        f"Voice and tone:\n"
        f"- Smart and knowledgeable, like a baseball lifer who also happens to be funny\n"
        f"- Punchy but not click-baity — no 'You won't believe...' or 'This changes everything'\n"
        f"- Dry wit and light humor are welcome — a well-placed joke lands better than forced enthusiasm\n"
        f"- Opinionated — make a call, take a stance, express genuine excitement or skepticism\n"
        f"- Conversational, like a text to a friend who really knows baseball\n\n"
        f"Content rules:\n"
        f"- Lead with the most surprising or compelling detail, not the obvious headline\n"
        f"- If there is Statcast data (exit velocity, spin rate, sprint speed, etc.), make that the hook\n"
        f"- Favor players who aren't household names — obscure player doing something impressive is gold\n"
        f"- Be under 260 characters so there's room for a link\n"
        f"- Use 0-1 hashtags max\n"
        f"- Never say you lack information — always produce a usable tweet\n\n"
        f"Return only the tweet text, nothing else."
    )
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    tweet = msg.content[0].text.strip()
    return f"{tweet} {article['link']} rankle.dev"


def generate_promo_tweet():
    prompt = (
        f"Generate a promotional tweet for Rankle.\n\n"
        f"{RANKLE_DESCRIPTION}\n\n"
        f"The tweet should:\n"
        f"- Sound like a smart, funny baseball fan who built something cool — not a startup\n"
        f"- Light humor is welcome, forced enthusiasm is not\n"
        f"- Be under 280 characters total\n"
        f"- Include the URL rankle.dev naturally\n"
        f"- Use 0-1 hashtags max\n"
        f"- Never use phrases like 'game-changing', 'revolutionize', or 'unlock'\n\n"
        f"Return only the tweet text, nothing else."
    )
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def approval_keyboard(tweet_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Post", callback_data=f"post:{tweet_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{tweet_id}"),
            InlineKeyboardButton("⏭️ Skip", callback_data=f"skip:{tweet_id}"),
        ]
    ])


async def send_draft(app, draft, tweet_id):
    pending = load_pending()
    pending[tweet_id] = {"text": draft, "awaiting_edit": False}
    save_pending(pending)
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=f"Draft tweet ({len(draft)} chars):\n\n{draft}",
        reply_markup=approval_keyboard(tweet_id)
    )


async def check_feeds(app):
    logging.info("Checking RSS feeds...")
    articles, seen = fetch_articles()
    if not articles:
        logging.info("No new articles found.")
        return
    top_prospects = load_top_prospects(top_n=20)

    # Filter: remove college articles and top-20 prospect articles
    filtered = []
    for article in articles:
        title_lower = article["title"].lower()
        if is_college_article(article):
            logging.info(f"Skipping college article: {article['title']}")
            seen.add(article["link"])
        elif is_mlb_player_article(article):
            logging.info(f"Skipping MLB player article: {article['title']}")
            seen.add(article["link"])
        elif any(name in title_lower for name in top_prospects):
            logging.info(f"Skipping top prospect article: {article['title']}")
            seen.add(article["link"])
        else:
            filtered.append(article)
    save_seen(seen)

    # Filter: keep only prospect-relevant articles
    logging.info(f"{len(filtered)} articles after keyword filters. Running prospect relevance screen...")
    prospect_articles = filter_prospect_articles(filtered)
    logging.info(f"{len(prospect_articles)} articles passed prospect screen.")

    # Cap at MAX_DRAFTS_PER_CHECK
    prospect_articles = prospect_articles[:MAX_DRAFTS_PER_CHECK]

    for article in prospect_articles:
        try:
            draft = generate_news_tweet(article)
            tweet_id = f"news_{abs(hash(article['link']))}"
            await send_draft(app, draft, tweet_id)
            seen.add(article["link"])
            save_seen(seen)
        except Exception as e:
            logging.error(f"Error generating tweet: {e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, tweet_id = query.data.split(":", 1)
    pending = load_pending()

    if tweet_id not in pending:
        await query.edit_message_text("This draft has expired.")
        return

    draft = pending[tweet_id]["text"]

    if action == "post":
        try:
            twitter.create_tweet(text=draft)
            del pending[tweet_id]
            save_pending(pending)
            await query.edit_message_text(f"✅ Posted!\n\n{draft}")
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to post: {e}")

    elif action == "skip":
        del pending[tweet_id]
        save_pending(pending)
        await query.edit_message_text(f"⏭️ Skipped.\n\n{draft}")

    elif action == "edit":
        pending[tweet_id]["awaiting_edit"] = True
        save_pending(pending)
        await query.edit_message_text(
            f"✏️ Send your edited version of this tweet:\n\n{draft}"
        )
        context.user_data["editing_tweet_id"] = tweet_id


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tweet_id = context.user_data.get("editing_tweet_id")
    if not tweet_id:
        return
    pending = load_pending()
    if tweet_id not in pending or not pending[tweet_id].get("awaiting_edit"):
        return

    new_text = update.message.text.strip()
    pending[tweet_id]["text"] = new_text
    pending[tweet_id]["awaiting_edit"] = False
    save_pending(pending)
    context.user_data.pop("editing_tweet_id", None)

    await update.message.reply_text(
        f"📝 *Updated draft* ({len(new_text)} chars):\n\n{new_text}",
        parse_mode="Markdown",
        reply_markup=approval_keyboard(tweet_id)
    )


async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generating a Rankle promo tweet...")
    try:
        draft = generate_promo_tweet()
        tweet_id = f"promo_{os.urandom(4).hex()}"
        await send_draft(context.application, draft, tweet_id)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def check_feeds_job(context: ContextTypes.DEFAULT_TYPE):
    await check_feeds(context.application)


async def gems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Searching for hidden gems in the minors...")
    try:
        gems = find_gems()
        if not gems:
            await update.message.reply_text("No hidden gems found right now — try again later in the season when there's more data.")
            return
        for player, draft in gems[:5]:
            tweet_id = f"gem_{abs(hash(player['name']))}"
            await send_draft(context.application, draft, tweet_id)
            await asyncio.sleep(2)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking RSS feeds now...")
    await check_feeds(context.application)


async def checkupdates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a check of all ranking source pages for changes."""
    await update.message.reply_text("Checking ranking sources for updates...")
    try:
        changed, errors = await asyncio.get_event_loop().run_in_executor(
            None, check_for_updates
        )
        lines = []
        if changed:
            lines.append("🔔 *Changes detected:*")
            for s in changed:
                lines.append(f"  • {s}")
        else:
            lines.append("✅ No changes detected.")
        if errors:
            lines.append("\n⚠️ *Errors:*")
            for s, e in errors:
                lines.append(f"  • {s}: {e}")

        status = get_status()
        unconfigured = [r["source"] for r in status if not r["url"]]
        if unconfigured:
            lines.append(f"\n⏭️ *Not configured ({len(unconfigured)}):*")
            lines.append("  " + ", ".join(unconfigured))

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def check_sources_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job — runs twice daily, notifies if any source has changed."""
    try:
        changed, errors = await asyncio.get_event_loop().run_in_executor(
            None, check_for_updates
        )
        if changed:
            lines = ["🔔 *Ranking source update detected:*"]
            for s in changed:
                lines.append(f"  • {s}")
            lines.append("\nTime to update the data.")
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
        if errors:
            lines = ["⚠️ *Source monitor errors:*"]
            for s, e in errors:
                lines.append(f"  • {s}: {e}")
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.error(f"check_sources_job error: {e}")


async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /CHW, /NYY, /LAD, etc. — generate a team prospects graphic."""
    raw = update.message.text.split()[0][1:]   # strip leading /
    raw = raw.split("@")[0]                    # strip @botname suffix
    team_code = raw.upper()

    if team_code not in TEAMS:
        known = ", ".join(f"/{t.lower()}" for t in sorted(TEAMS))
        await update.message.reply_text(
            f"Unknown team: {team_code}\n\nValid codes:\n{known}"
        )
        return

    team_name = TEAMS[team_code][0]
    await update.message.reply_text(f"Generating {team_name} prospects graphic…")
    try:
        buf = generate_team_graphic(team_code)
        await update.message.reply_photo(
            photo=buf,
            caption=f"{team_name} top prospects — consensus rankings at rankle.dev"
        )
    except Exception as e:
        logging.error(f"team_command error for {team_code}: {e}")
        await update.message.reply_text(f"Error generating graphic: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Rankle Bot is running!\n\n"
        "/check — fetch latest prospect news now\n"
        "/checkupdates — check ranking sources for list updates\n"
        "/promo — generate a Rankle promo tweet\n"
        "/gems — find hidden gem prospects in the minors\n"
        "/chw, /nyy, /lad, etc. — generate a team prospects graphic"
    )


def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("checkupdates", checkupdates_command))
    app.add_handler(CommandHandler("promo", promo_command))
    app.add_handler(CommandHandler("gems", gems_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    # Catch-all for /teamcode commands — must be last so named commands take priority
    app.add_handler(MessageHandler(filters.COMMAND, team_command))

    app.job_queue.run_repeating(check_feeds_job, interval=6 * 3600, first=10)
    # Check ranking source pages twice daily (every 12 hours, first run after 5 min)
    app.job_queue.run_repeating(check_sources_job, interval=12 * 3600, first=300)

    logging.info("Rankle Bot started. Checking feeds every 6 hours.")
    app.run_polling()


if __name__ == "__main__":
    main()
