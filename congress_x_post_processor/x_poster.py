"""
XPoster: Post new congressional legislation to X (Twitter).

Usage:
    from x_poster import XPoster
    poster = XPoster()
    poster.post_bill(docnum, title, link)

This file is not used by the main monitor script. Integrate as needed.
"""

import logging
from typing import Optional

try:
    import tweepy
except ImportError:
    tweepy = None

LOG = logging.getLogger("x_poster")

class XPoster:
    def __init__(self):
        from typing import Any
        self.client: Optional[Any] = None
        try:
            from api.x_api_call import get_twitter_credentials  # type: ignore
        except Exception:
            get_twitter_credentials = None
        creds = get_twitter_credentials() if get_twitter_credentials else None
        if creds and tweepy:
            ck = creds.get("api_key")
            cs = creds.get("api_secret")
            at = creds.get("access_token")
            ats = creds.get("access_token_secret")
            if ck and cs and at and ats:
                try:
                    self.client = tweepy.Client(
                        consumer_key=ck,
                        consumer_secret=cs,
                        access_token=at,
                        access_token_secret=ats,
                    )
                except Exception:
                    LOG.exception("Failed to create Tweepy client")
        else:
            LOG.info("No credentials or Tweepy not installed; running in dry-run mode")

    def post_bill(self, docnum: str, title: str, link: str) -> bool:
        text = self.build_tweet_text(docnum, title, link)
        if not self.client:
            LOG.info("DRY-RUN: %s", text)
            return True
        try:
            resp = self.client.create_tweet(text=text)
            LOG.info("Posted tweet id=%s", getattr(resp, "data", {}).get("id"))
            return True
        except Exception:
            LOG.exception("Failed to post to X")
            return False

    @staticmethod
    def build_tweet_text(docnum: Optional[str], title: str, link: str) -> str:
        if docnum:
            text = f"New legislation posted: {docnum} — {link}"
        else:
            text = f"New legislation posted: {title} — {link}"
        if len(text) > 270:
            text = text[:266] + "..."
        return text
