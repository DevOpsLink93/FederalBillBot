"""
XPoster: Post new congressional legislation to X (Twitter).

Usage:
    from x_poster import XPoster
    poster = XPoster()
    poster.post_bill(bill_number, date_introduced, sponsor, summary, link)
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
            from api.x_api_call import get_x_api_client  # type: ignore
            # Get the X API client directly
            self.client = get_x_api_client()
            LOG.info("X API client initialized successfully")
        except ImportError as e:
            LOG.warning(f"Failed to import x_api_call: {e}")
            LOG.info("Running in test mode (posting disabled)")
        except Exception as e:
            LOG.exception(f"Failed to initialize X API client: {e}")
            LOG.info("Running in test mode (posting disabled)")
        
        if not self.client and tweepy:
            LOG.warning("Tweepy is available but no client was created. Running in test mode.")
        elif not tweepy:
            LOG.warning("Tweepy not installed. Install with: pip install tweepy")
            LOG.info("Running in test mode (posting disabled)")

    def post_bill(self, bill_number: str, date_introduced: str, sponsor: str, summary: str, link: str) -> bool:
        """
        Print bill information and post to X.com.
        For testing, actual posting is commented out.
        """
        # Print all values in order as specified
        print(f"Bill Number: {bill_number}")
        print(f"Date Introduced: {date_introduced}")
        print(f"Sponsor: {sponsor}")
        print(f"Summary: {summary}")
        print(f"Link: {link}")
        print()  # Empty line for readability
        
        # Build the formatted text for posting
        text = self.build_x_post_text(bill_number, date_introduced, sponsor, summary, link)
        
        # Print what would be posted
        print(f"Formatted text for X.com:")
        print(text)
        print()
        
        # TESTING MODE: Comment out actual posting
        # Uncomment the code below to enable actual posting to X.com
        """
        if not self.client:
            LOG.warning("DRY-RUN: Would post to X: %s", text)
            return False
        
        try:
            LOG.info("Posting to X: %s", text)
            resp = self.client.create_tweet(text=text)
            tweet_id = getattr(resp, "data", {}).get("id") if hasattr(resp, "data") else None
            if tweet_id:
                LOG.info("Successfully posted to X! Tweet ID: %s", tweet_id)
                print(f"Post to X successful! X ID: {tweet_id}")
            else:
                LOG.info("Posted to X (response: %s)", resp)
                print("Post to X successful!")
            return True
        except Exception as e:
            LOG.exception("Failed to post to X")
            print(f"Post to X failed: {e}")
            return False
        """
        
        # Return True for testing purposes (simulating successful post)
        LOG.info("TEST MODE: Posting disabled. Would have posted to X.")
        return True

    @staticmethod
    def build_x_post_text(bill_number: str, date_introduced: str, sponsor: str, summary: str, link: str) -> str:
        """
        Build formatted post text with all bill information.
        Format: Bill Number, Date Introduced, Sponsor, Summary, Link
        """
        # Build the text with all information
        text = f"Bill Number: {bill_number}\n"
        text += f"Date Introduced: {date_introduced}\n"
        text += f"Sponsor: {sponsor}\n"
        text += f"Summary: {summary}\n"
        text += f"Link: {link}"
        
        # X character limit is 280, but we need to handle longer content
        if len(text) > 280:
            # Calculate available space for summary (most likely to be long)
            base_text = f"Bill Number: {bill_number}\nDate Introduced: {date_introduced}\nSponsor: {sponsor}\nSummary: \nLink: {link}"
            base_length = len(base_text)
            available_for_summary = 280 - base_length - 10  # Leave some buffer
            
            if available_for_summary > 20:  # Only truncate if we have reasonable space
                summary_truncated = summary[:available_for_summary - 3] + "..."
                text = f"Bill Number: {bill_number}\nDate Introduced: {date_introduced}\nSponsor: {sponsor}\nSummary: {summary_truncated}\nLink: {link}"
            else:
                # If still too long, truncate more aggressively
                # Keep bill number, date, sponsor, and link, truncate summary heavily
                max_summary = 280 - base_length + len(summary) - 20
                if max_summary > 10:
                    summary_truncated = summary[:max_summary - 3] + "..."
                    text = f"Bill Number: {bill_number}\nDate Introduced: {date_introduced}\nSponsor: {sponsor}\nSummary: {summary_truncated}\nLink: {link}"
                else:
                    # Last resort: truncate everything
                    text = text[:277] + "..."
        
        return text
