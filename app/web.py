import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify
from app.models import (
    init_db, Subreddit, Keyword, TrackedPost, DraftReply,
    AccountMetric, ActivityLog
)
from app.llm import generate_reply
from app.scheduler import (
    start_scheduler, stop_scheduler, scan_all_subreddits,
    schedule_reply, collect_metrics
)

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
)


@app.before_request
def _ensure_db():
    init_db()


# ── Dashboard ────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    posts_total = TrackedPost.select().count()
    posts_new = TrackedPost.select().where(TrackedPost.status == "new").count()
    replies_sent = DraftReply.select().where(DraftReply.status == "sent").count()
    replies_scheduled = DraftReply.select().where(DraftReply.status == "scheduled").count()

    latest_metric = AccountMetric.select().order_by(AccountMetric.timestamp.desc()).first()
    metrics_history = list(
        AccountMetric.select()
        .order_by(AccountMetric.timestamp.desc())
        .limit(168)  # 7 days hourly
    )

    recent_logs = list(ActivityLog.select().order_by(ActivityLog.timestamp.desc()).limit(20))

    return render_template("dashboard.html",
        posts_total=posts_total,
        posts_new=posts_new,
        replies_sent=replies_sent,
        replies_scheduled=replies_scheduled,
        latest_metric=latest_metric,
        metrics_history=metrics_history,
        recent_logs=recent_logs,
    )


# ── Subreddits ───────────────────────────────────────────────────────
@app.route("/subreddits")
def subreddits_page():
    subs = list(Subreddit.select().order_by(Subreddit.name))
    return render_template("subreddits.html", subreddits=subs)


@app.route("/subreddits/add", methods=["POST"])
def add_subreddit():
    name = request.form.get("name", "").strip().lower()
    if name:
        Subreddit.get_or_create(name=name)
    return redirect(url_for("subreddits_page"))


@app.route("/subreddits/<int:sub_id>/toggle", methods=["POST"])
def toggle_subreddit(sub_id):
    sub = Subreddit.get_by_id(sub_id)
    sub.enabled = not sub.enabled
    sub.save()
    return redirect(url_for("subreddits_page"))


@app.route("/subreddits/<int:sub_id>/delete", methods=["POST"])
def delete_subreddit(sub_id):
    Subreddit.delete_by_id(sub_id)
    return redirect(url_for("subreddits_page"))


# ── Keywords ─────────────────────────────────────────────────────────
@app.route("/keywords")
def keywords_page():
    kws = list(Keyword.select().order_by(Keyword.word))
    return render_template("keywords.html", keywords=kws)


@app.route("/keywords/add", methods=["POST"])
def add_keyword():
    word = request.form.get("word", "").strip().lower()
    subreddit = request.form.get("subreddit", "*").strip().lower() or "*"
    if word:
        Keyword.create(word=word, subreddit=subreddit)
    return redirect(url_for("keywords_page"))


@app.route("/keywords/<int:kw_id>/delete", methods=["POST"])
def delete_keyword(kw_id):
    Keyword.delete_by_id(kw_id)
    return redirect(url_for("keywords_page"))


# ── Posts ─────────────────────────────────────────────────────────────
@app.route("/posts")
def posts_page():
    status = request.args.get("status", "new")
    posts = list(
        TrackedPost.select()
        .where(TrackedPost.status == status)
        .order_by(TrackedPost.discovered_at.desc())
        .limit(50)
    )
    return render_template("posts.html", posts=posts, current_status=status)


@app.route("/posts/<post_id>/generate", methods=["POST"])
def generate_reply_for_post(post_id):
    post = TrackedPost.get(TrackedPost.reddit_id == post_id)
    try:
        body = generate_reply(
            post.title,
            "",  # We don't store selftext to save space; title + keywords suffice
            post.subreddit,
            post.matched_keywords.split(","),
        )
        draft = DraftReply.create(post=post.reddit_id, body=body)
        post.status = "draft"
        post.save()
        return redirect(url_for("draft_page", draft_id=draft.id))
    except Exception as e:
        ActivityLog.create(action="error", detail=f"LLM error for {post_id}: {e}")
        return redirect(url_for("posts_page"))


@app.route("/posts/<post_id>/skip", methods=["POST"])
def skip_post(post_id):
    post = TrackedPost.get(TrackedPost.reddit_id == post_id)
    post.status = "skipped"
    post.save()
    return redirect(url_for("posts_page"))


# ── Drafts ────────────────────────────────────────────────────────────
@app.route("/drafts")
def drafts_page():
    drafts = list(
        DraftReply.select()
        .order_by(DraftReply.created_at.desc())
        .limit(50)
    )
    posts_map = {}
    for d in drafts:
        if d.post not in posts_map:
            p = TrackedPost.get_or_none(TrackedPost.reddit_id == d.post)
            posts_map[d.post] = p
    return render_template("drafts.html", drafts=drafts, posts_map=posts_map)


@app.route("/drafts/<int:draft_id>")
def draft_page(draft_id):
    draft = DraftReply.get_by_id(draft_id)
    post = TrackedPost.get_or_none(TrackedPost.reddit_id == draft.post)
    return render_template("draft_detail.html", draft=draft, post=post)


@app.route("/drafts/<int:draft_id>/edit", methods=["POST"])
def edit_draft(draft_id):
    draft = DraftReply.get_by_id(draft_id)
    draft.body = request.form.get("body", draft.body)
    draft.save()
    return redirect(url_for("draft_page", draft_id=draft_id))


@app.route("/drafts/<int:draft_id>/schedule", methods=["POST"])
def schedule_draft(draft_id):
    delay = schedule_reply(draft_id)
    post = DraftReply.get_by_id(draft_id)
    tp = TrackedPost.get_or_none(TrackedPost.reddit_id == post.post)
    if tp:
        tp.status = "scheduled"
        tp.save()
    return redirect(url_for("drafts_page"))


@app.route("/drafts/<int:draft_id>/delete", methods=["POST"])
def delete_draft(draft_id):
    draft = DraftReply.get_by_id(draft_id)
    tp = TrackedPost.get_or_none(TrackedPost.reddit_id == draft.post)
    if tp and tp.status == "draft":
        tp.status = "new"
        tp.save()
    draft.delete_instance()
    return redirect(url_for("drafts_page"))


# ── Actions ───────────────────────────────────────────────────────────
@app.route("/actions/scan", methods=["POST"])
def trigger_scan():
    scan_all_subreddits()
    return redirect(url_for("posts_page"))


@app.route("/actions/metrics", methods=["POST"])
def trigger_metrics():
    collect_metrics()
    return redirect(url_for("dashboard"))


# ── API (for AJAX) ───────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    latest = AccountMetric.select().order_by(AccountMetric.timestamp.desc()).first()
    return jsonify({
        "posts_new": TrackedPost.select().where(TrackedPost.status == "new").count(),
        "replies_sent": DraftReply.select().where(DraftReply.status == "sent").count(),
        "karma_comment": latest.karma_comment if latest else 0,
        "karma_link": latest.karma_link if latest else 0,
    })
