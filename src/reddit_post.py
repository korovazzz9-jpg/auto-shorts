"""Постит ссылку на видео в Reddit (бесплатно, через PRAW)."""
import os

import praw


def post_link(title: str, url: str) -> str:
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent="60SecFacts auto-poster (by u/" + os.environ["REDDIT_USERNAME"] + ")",
    )
    subreddit_name = os.environ.get("REDDIT_SUBREDDIT", "Facts")
    submission = reddit.subreddit(subreddit_name).submit(title=title[:300], url=url)
    print(f"Posted to r/{subreddit_name}: {submission.shortlink}")
    return submission.shortlink
