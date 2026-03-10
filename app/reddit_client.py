import os
import time
import praw
from app.models import ActivityLog


def get_reddit():
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "RedditPresence/1.0"),
    )


def fetch_account_info(reddit):
    me = reddit.user.me()
    return {
        "name": me.name,
        "karma_comment": me.comment_karma,
        "karma_link": me.link_karma,
    }


def scan_subreddit(reddit, subreddit_name, keywords, limit=25):
    """Scan a subreddit for posts matching keywords. Returns list of matching submissions."""
    matches = []
    try:
        sub = reddit.subreddit(subreddit_name)
        for submission in sub.new(limit=limit):
            text = f"{submission.title} {submission.selftext}".lower()
            matched = [kw for kw in keywords if kw.lower() in text]
            if matched:
                matches.append({
                    "id": submission.id,
                    "title": submission.title,
                    "selftext": submission.selftext[:2000],
                    "url": f"https://reddit.com{submission.permalink}",
                    "author": str(submission.author) if submission.author else "[deleted]",
                    "score": submission.score,
                    "subreddit": subreddit_name,
                    "matched_keywords": matched,
                    "num_comments": submission.num_comments,
                    "created_utc": submission.created_utc,
                })
        ActivityLog.create(action="scan", detail=f"r/{subreddit_name}: {len(matches)} matches from {limit} posts")
    except Exception as e:
        ActivityLog.create(action="error", detail=f"Scan r/{subreddit_name} failed: {e}")
    return matches


def post_comment(reddit, post_id, body):
    """Post a comment on a submission. Respects rate limits."""
    try:
        submission = reddit.submission(id=post_id)
        comment = submission.reply(body)
        ActivityLog.create(action="reply", detail=f"Replied to {post_id}")
        return {"success": True, "comment_id": comment.id}
    except praw.exceptions.RedditAPIException as e:
        # Handle rate limiting
        for item in e.items:
            if item.error_type == "RATELIMIT":
                wait = _parse_ratelimit_wait(item.message)
                ActivityLog.create(action="error", detail=f"Rate limited, need to wait {wait}s")
                return {"success": False, "error": "rate_limited", "wait_seconds": wait}
        ActivityLog.create(action="error", detail=f"API error posting to {post_id}: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        ActivityLog.create(action="error", detail=f"Error posting to {post_id}: {e}")
        return {"success": False, "error": str(e)}


def _parse_ratelimit_wait(message):
    """Parse wait time from Reddit rate limit message."""
    import re
    match = re.search(r"(\d+)\s*minute", message)
    if match:
        return int(match.group(1)) * 60
    match = re.search(r"(\d+)\s*second", message)
    if match:
        return int(match.group(1))
    return 600  # default 10 min
