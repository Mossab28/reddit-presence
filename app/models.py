import datetime
from peewee import (
    SqliteDatabase, Model, CharField, TextField, IntegerField,
    DateTimeField, BooleanField, FloatField
)

db = SqliteDatabase("reddit_presence.db")


class BaseModel(Model):
    class Meta:
        database = db


class Subreddit(BaseModel):
    name = CharField(unique=True)
    enabled = BooleanField(default=True)
    added_at = DateTimeField(default=datetime.datetime.now)


class Keyword(BaseModel):
    word = CharField()
    subreddit = CharField(default="*")  # "*" means all subreddits
    enabled = BooleanField(default=True)


class TrackedPost(BaseModel):
    reddit_id = CharField(unique=True)
    subreddit = CharField()
    title = TextField()
    url = TextField()
    author = CharField()
    score = IntegerField(default=0)
    matched_keywords = TextField(default="")
    relevance_score = FloatField(default=0.0)
    discovered_at = DateTimeField(default=datetime.datetime.now)
    status = CharField(default="new")  # new, draft, scheduled, replied, skipped


class DraftReply(BaseModel):
    post = CharField()  # TrackedPost reddit_id
    body = TextField()
    approved = BooleanField(default=False)
    scheduled_at = DateTimeField(null=True)
    sent_at = DateTimeField(null=True)
    status = CharField(default="draft")  # draft, approved, scheduled, sent, failed
    created_at = DateTimeField(default=datetime.datetime.now)


class AccountMetric(BaseModel):
    timestamp = DateTimeField(default=datetime.datetime.now)
    karma_comment = IntegerField(default=0)
    karma_link = IntegerField(default=0)
    followers = IntegerField(default=0)


class ActivityLog(BaseModel):
    action = CharField()  # scan, reply, error
    detail = TextField(default="")
    timestamp = DateTimeField(default=datetime.datetime.now)


def init_db():
    db.connect(reuse_if_open=True)
    db.create_tables([
        Subreddit, Keyword, TrackedPost, DraftReply,
        AccountMetric, ActivityLog
    ])
