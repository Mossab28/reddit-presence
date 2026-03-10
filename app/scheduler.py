import random
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from app.models import (
    db, Subreddit, Keyword, TrackedPost, DraftReply,
    AccountMetric, ActivityLog
)
from app.reddit_client import get_reddit, scan_subreddit, post_comment, fetch_account_info

scheduler = BackgroundScheduler()

# Global config for sending behavior
MIN_DELAY_MINUTES = 5
MAX_DELAY_MINUTES = 45
MAX_REPLIES_PER_HOUR = 3

_reply_count_this_hour = 0
_hour_start = datetime.datetime.now()


def scan_all_subreddits():
    """Scan all enabled subreddits for matching posts."""
    try:
        reddit = get_reddit()
        subreddits = Subreddit.select().where(Subreddit.enabled == True)
        all_keywords = [kw.word for kw in Keyword.select().where(Keyword.enabled == True)]

        if not all_keywords:
            ActivityLog.create(action="scan", detail="No keywords configured, skipping scan")
            return

        for sub in subreddits:
            # Get subreddit-specific + global keywords
            sub_keywords = [
                kw.word for kw in Keyword.select().where(
                    (Keyword.enabled == True) &
                    ((Keyword.subreddit == sub.name) | (Keyword.subreddit == "*"))
                )
            ]
            matches = scan_subreddit(reddit, sub.name, sub_keywords)

            for m in matches:
                # Skip if already tracked
                if TrackedPost.select().where(TrackedPost.reddit_id == m["id"]).exists():
                    continue
                TrackedPost.create(
                    reddit_id=m["id"],
                    subreddit=m["subreddit"],
                    title=m["title"],
                    url=m["url"],
                    author=m["author"],
                    score=m["score"],
                    matched_keywords=",".join(m["matched_keywords"]),
                )

        ActivityLog.create(action="scan", detail="Full scan completed")
    except Exception as e:
        ActivityLog.create(action="error", detail=f"Scan error: {e}")


def send_scheduled_replies():
    """Send approved replies that are due."""
    global _reply_count_this_hour, _hour_start

    now = datetime.datetime.now()
    # Reset hourly counter
    if (now - _hour_start).total_seconds() > 3600:
        _reply_count_this_hour = 0
        _hour_start = now

    if _reply_count_this_hour >= MAX_REPLIES_PER_HOUR:
        return

    due_replies = (
        DraftReply.select()
        .where(
            (DraftReply.status == "scheduled") &
            (DraftReply.scheduled_at <= now)
        )
        .order_by(DraftReply.scheduled_at)
    )

    reddit = None
    for reply in due_replies:
        if _reply_count_this_hour >= MAX_REPLIES_PER_HOUR:
            break
        if reddit is None:
            reddit = get_reddit()
        result = post_comment(reddit, reply.post, reply.body)
        if result["success"]:
            reply.status = "sent"
            reply.sent_at = now
            reply.save()
            _reply_count_this_hour += 1
        elif result.get("error") == "rate_limited":
            break  # Stop trying, we're rate limited
        else:
            reply.status = "failed"
            reply.save()


def collect_metrics():
    """Collect account metrics."""
    try:
        reddit = get_reddit()
        info = fetch_account_info(reddit)
        AccountMetric.create(
            karma_comment=info["karma_comment"],
            karma_link=info["karma_link"],
        )
    except Exception as e:
        ActivityLog.create(action="error", detail=f"Metrics error: {e}")


def schedule_reply(draft_id):
    """Schedule a draft reply with a random human-like delay."""
    draft = DraftReply.get_by_id(draft_id)
    delay = random.randint(MIN_DELAY_MINUTES, MAX_DELAY_MINUTES)
    draft.scheduled_at = datetime.datetime.now() + datetime.timedelta(minutes=delay)
    draft.status = "scheduled"
    draft.save()
    return delay


def start_scheduler():
    if not scheduler.running:
        # Scan every 15 minutes
        scheduler.add_job(scan_all_subreddits, "interval", minutes=15, id="scan", replace_existing=True)
        # Check for due replies every 2 minutes
        scheduler.add_job(send_scheduled_replies, "interval", minutes=2, id="send", replace_existing=True)
        # Collect metrics every hour
        scheduler.add_job(collect_metrics, "interval", hours=1, id="metrics", replace_existing=True)
        scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
