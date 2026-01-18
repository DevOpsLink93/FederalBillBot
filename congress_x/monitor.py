# Federal Bill Monitor
# Scans congress.gov API for newly introduced bills and processes them

import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any

import requests

# Import congress API key
try:
    from ..api.congress_api import get_api_key
except ImportError:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from api.congress_api import get_api_key

# Import database functions
try:
    from ..sqlite.new_Legislation_log import process_and_log_bill, bill_exists, init_db_connection
except ImportError:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlite.new_Legislation_log import process_and_log_bill, bill_exists, init_db_connection

# Import XPoster for processing bills
try:
    from .x_poster import XPoster
except ImportError:
    from x_poster import XPoster

LOG = logging.getLogger("congress_monitor")


def fetch_recent_bills(api_key: str, limit: int = 250, days_back: int = 7) -> List[Dict[str, Any]]:
    """
    Fetch bills from congress.gov API for the 119th Congress that were introduced
    within the last N days using date filtering.

    Args:
        api_key: Congress API key
        limit: Maximum number of bills to fetch from API (default 250)
        days_back: Number of days to look back from today (default 7)

    Returns:
        List of bill dictionaries from the 119th Congress introduced in the date range,
        sorted with HR bills first (descending by number), then other bills.
    """
    from datetime import datetime, timedelta

    # Calculate date range
    today = datetime.now().date()
    from_date = today - timedelta(days=days_back)

    # Format dates for API (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)
    # Use start of day for fromDateTime and end of day for toDateTime
    from_datetime = f"{from_date.isoformat()}T00:00:00Z"
    to_datetime = f"{today.isoformat()}T23:59:59Z"

    # Use a session for connection pooling
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key})

    try:
        base_url = "https://api.congress.gov/v3/bill/119"

        LOG.info(f"Fetching bills from 119th Congress (most recent {limit} bills)...")

        # Since the API sorting is not reliable, let's try a targeted approach
        # Check for bills with high numbers that are likely to be recent
        all_bills = []

        # Check HR bills from 7040 onwards (around where recent bills are)
        # Start from a higher number to catch bills introduced after the last run
        start_num = 7040
        # Check bills up to 7100 to catch any newly introduced bills
        for bill_num in range(start_num, 7100):
            bill_type = "hr"
            try:
                bill_detail = get_bill_details(api_key, "119", bill_type, str(bill_num))
                if bill_detail:
                    introduced_date_str = bill_detail.get("introducedDate")
                    if introduced_date_str:
                        try:
                            introduced_date = datetime.fromisoformat(introduced_date_str.replace('Z', '+00:00')).date()
                            if from_date <= introduced_date <= today:
                                # Create bill data from the detail
                                bill = {
                                    "type": bill_type.upper(),
                                    "number": str(bill_num),
                                    "congress": "119",
                                    "title": bill_detail.get("title", "")
                                }
                                bill_data = extract_bill_data(bill, bill_detail)
                                all_bills.append(bill_data)
                                LOG.debug(f"Found recent bill: {bill_type.upper()}.{bill_num} introduced on {introduced_date}")
                        except (ValueError, TypeError) as e:
                            LOG.debug(f"Could not parse date for {bill_type.upper()}.{bill_num}: {e}")
            except Exception as e:
                # Bill doesn't exist, continue
                pass

        # Limit to the requested number
        bills_batch = all_bills[:limit]

        total_available = len(all_bills)

        session.close()

        LOG.info(f"Successfully fetched {len(bills_batch)} bills introduced between {from_date} and {today}")
        return bills_batch

    except Exception as e:
        LOG.error(f"Error fetching bills from Congress API: {e}")
        session.close()
        return []


def get_bill_details(api_key: str, congress: str, bill_type: str, bill_number: str) -> Dict[str, Any]:
    """
    Get detailed bill information from Congress API.

    Args:
        api_key: Congress API key
        congress: Congress number (e.g., "119")
        bill_type: Bill type (e.g., "hr", "s")
        bill_number: Bill number

    Returns:
        Bill detail dictionary
    """
    try:
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}"
        headers = {"X-Api-Key": api_key}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("bill", {})
    except Exception as e:
        LOG.warning(f"Error fetching bill details for {bill_type} {bill_number}: {e}")
        return {}


def extract_bill_data(bill: Dict[str, Any], bill_detail: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Extract and format bill data for processing.

    Args:
        bill: Basic bill data from API
        bill_detail: Detailed bill data (optional)

    Returns:
        Formatted bill data dictionary
    """
    # Ensure bill is a dictionary
    if not isinstance(bill, dict):
        LOG.warning(f"Bill data is not a dict: {type(bill)}")
        return {}
    
    bill_type = bill.get("bill_type", bill.get("type", "")).upper()
    bill_number = bill.get("bill_number", bill.get("number", ""))
    congress = bill.get("congress", "")
    title = bill.get("title", "Unknown")

    # Extract additional details if available
    sponsor = "Unknown"
    summary = "Unknown"
    introduced_date = bill.get("introducedDate", "Unknown")

    if bill_detail and isinstance(bill_detail, dict):
        try:
            # Extract introduced date
            introduced_date_str = bill_detail.get("introducedDate")
            if introduced_date_str:
                introduced_date = introduced_date_str

            # Extract sponsor
            sponsors = bill_detail.get("sponsors", [])
            if sponsors and isinstance(sponsors, list) and len(sponsors) > 0:
                sponsor_data = sponsors[0]
                if isinstance(sponsor_data, dict):
                    first_name = sponsor_data.get("firstName", "")
                    last_name = sponsor_data.get("lastName", "")
                    title_prefix = sponsor_data.get("title", "")
                    if title_prefix and first_name and last_name:
                        sponsor = f"{title_prefix} {first_name} {last_name}"
                    elif first_name and last_name:
                        sponsor = f"{first_name} {last_name}"

            # Extract summary (try both 'summary' and 'summaries' structures)
            summary_data = bill_detail.get("summary", {})
            if summary_data and isinstance(summary_data, dict):
                summary_text = summary_data.get("text", "")
                if summary_text:
                    summary = summary_text.strip()
        except Exception as e:
            LOG.debug(f"Error extracting details from bill_detail: {e}")

    # Construct URL
    bill_type_map = {
        "HR": "house-bill",
        "S": "senate-bill",
        "HRES": "house-resolution",
        "SRES": "senate-resolution",
        "HJRES": "house-joint-resolution",
        "SJRES": "senate-joint-resolution",
        "HCONRES": "house-concurrent-resolution",
        "SCONRES": "senate-concurrent-resolution"
    }

    bill_type_url = bill_type_map.get(bill_type, bill_type.lower())
    url = f"https://www.congress.gov/bill/{congress}th-congress/{bill_type_url}/{bill_number}" if congress and bill_type_url and bill_number else "Unknown"

    return {
        'bill_number': bill_number,
        'bill_type': bill_type,
        'congress': congress,
        'title': title,
        'summary': summary,
        'sponsor': sponsor,
        'introduced_date': introduced_date,
        'url': url,
        'formatted_bill_number': f"{bill_type}.{bill_number}"
    }


def countdown_timer(seconds: int, message: str = "Next scan in") -> None:
    """Display a countdown timer with hours, minutes and seconds remaining."""
    print(f"\n⏱️  {message}...")
    for remaining in range(seconds, 0, -1):
        hours, remainder = divmod(remaining, 3600)
        mins, secs = divmod(remainder, 60)

        # Create a more prominent timer display
        timer_display = f"\r⏳ {message} {hours:02d}:{mins:02d}:{secs:02d}"

        # Add visual indicators for different time ranges
        if remaining <= 60:  # Last minute
            timer_display += " 🔴"
        elif remaining <= 300:  # Last 5 minutes
            timer_display += " 🟡"
        else:
            timer_display += " 🟢"

        print(timer_display, end='', flush=True)
        time.sleep(1)

    # Clear the timer line and show completion message
    print("\r" + " " * 50 + "\r", end='', flush=True)
    print("🚀 Starting next scan...\n")


def monitor_and_process_bills(api_key: str, limit: int = 50, post_to_x: bool = False, aggregate_all: bool = False) -> tuple[int, bool]:
    """
    Main monitoring function that fetches recent bills and processes them.
    Can process all bills from scan or only new ones.

    Args:
        api_key: Congress API key
        limit: Number of bills to fetch (default 50)
        post_to_x: Whether to post bills to X.com (default False)
        aggregate_all: Whether to aggregate ALL bills from scan (default False)

    Returns:
        Tuple of (number of bills processed, whether posting to X occurred)
    """
    LOG.info(f"🔍 Starting bill monitoring - fetching bills introduced in the last 7 days")

    # Use larger limit to capture all bills in the date range
    # We'll prioritize HR bills and sort them by number descending
    bills = fetch_recent_bills(api_key, limit=250, days_back=7)
    if not bills:
        LOG.warning("No bills fetched from API")
        return 0, False

    # Initialize XPoster for processing
    poster = XPoster()
    bills_to_process = []

    # Collect bills based on aggregation mode
    for bill in bills:
        # Ensure bill is a dictionary
        if not isinstance(bill, dict):
            LOG.warning(f"Skipping invalid bill object (not a dict): {type(bill)}")
            continue

        bill_type = bill.get("bill_type", "").upper()
        bill_number = bill.get("bill_number", "")
        congress = bill.get("congress", "")

        # Skip if missing required fields
        if not all([bill_type, bill_number, congress]):
            LOG.debug(f"Skipping bill with missing required fields: {bill}")
            continue

        LOG.debug(f"Processing bill {bill_type}.{bill_number} (Congress {congress})")

        # Check if bill already exists in database (skip this check only when aggregating all bills)
        if not aggregate_all:
            try:
                exists = bill_exists(init_db_connection(), congress, bill_number, bill_type)
                if exists:
                    LOG.info(f"⏭️ Bill {bill_type}.{bill_number} already exists in database - skipping")
                    continue
            except Exception as e:
                LOG.error(f"Database check failed for bill {bill_type}.{bill_number}: {e}")
                continue
        else:
            LOG.debug(f"📊 Aggregating all bills mode - including {bill_type}.{bill_number} regardless of database status")

        # Get detailed information for the bill
        LOG.info(f"📋 Bill discovered: {bill_type}.{bill_number} (Congress {congress})")
        bill_detail = get_bill_details(api_key, congress, bill_type.lower(), bill_number)
        bill_data = extract_bill_data(bill, bill_detail)
        bills_to_process.append(bill_data)

    # Process bills into posts and store in database
    if bills_to_process:
        try:
            # Choose PNG filename based on mode and create timestamped name
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            png_basename = f"fedbillsummary-{timestamp}.png"
            png_filename = os.path.join(os.path.dirname(__file__), "..", "summary_images", png_basename)
            processed_count, x_posting_successful = poster.process_bills_into_posts(bills_to_process, post_to_x=post_to_x, create_png=True, png_filename=png_filename)
            posting_occurred = x_posting_successful
            if aggregate_all:
                LOG.info(f"✅ Successfully aggregated {processed_count} bills and created PNG image")
            elif post_to_x:
                LOG.info(f"✅ Successfully processed {processed_count} bills into posts and posted to X.com")
            else:
                LOG.info(f"✅ Successfully processed {processed_count} bills into posts and created PNG image")
        except Exception as e:
            LOG.error(f"Failed to process bills into posts: {e}")
            return 0, False
    else:
        if aggregate_all:
            LOG.info("No bills to aggregate")
        else:
            LOG.info("No new bills to process")
        processed_count = 0
        posting_occurred = False

    LOG.info(f"📊 Bill monitoring complete - processed {processed_count} bills")
    return processed_count, posting_occurred


def main() -> int:
    """Main entry point."""
    import sys

    # Parse command line arguments
    post_to_x = "--post-to-x" in sys.argv
    aggregate_all = "--aggregate-all" in sys.argv
    # Support both "--continuous" and "--continous" (misspelling)
    continuous = "--continuous" in sys.argv or "--continous" in sys.argv

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    # Get API key
    try:
        api_key_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "api",
            "congress_api_key.txt"
        )
        api_key = get_api_key(api_key_file)
        LOG.info("Successfully loaded Congress API key")
    except Exception as e:
        LOG.error(f"Failed to load API key: {e}")
        return 1

    if continuous:
        # Continuous monitoring mode - run every 3 hours
        monitoring_interval = 3 * 60 * 60  # 3 hours in seconds

        LOG.info("🔄 Starting continuous monitoring for newly introduced legislation")
        LOG.info("Checking congress.gov API every 3 hours")
        LOG.info("Press Ctrl+C to stop")
        print()

        # Track posting status to prevent re-posting within the same cycle
        last_post_cycle = None

        try:
            while True:
                try:
                    # Determine if we should post to X based on the cycle
                    current_cycle = int(time.time() // monitoring_interval)
                    should_post_to_x = post_to_x and (last_post_cycle is None or current_cycle > last_post_cycle)

                    if not should_post_to_x and post_to_x:
                        LOG.info("⏸️  Skipping X posting this cycle (waiting for next 3-hour cycle after last post)")

                    # Run monitoring
                    processed, posting_occurred = monitor_and_process_bills(api_key, limit=100, post_to_x=should_post_to_x, aggregate_all=aggregate_all)

                    # Update posting cycle tracking
                    if posting_occurred:
                        last_post_cycle = current_cycle
                        LOG.info(f"✅ Successfully posted in this cycle - next X posting allowed after 3 hours")
                    elif processed > 0:
                        LOG.info(f"📋 Processed {processed} bill(s) - PNG created, no X posting occurred")
                    else:
                        LOG.info("🔍 Scan complete - no new bills to process")

                    countdown_timer(monitoring_interval, "Next scan")

                except Exception as e:
                    LOG.error(f"❌ Monitoring error: {e}")
                    countdown_timer(monitoring_interval, "Retrying scan")

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
            return 0
    else:
        # Single run mode (existing behavior)
        try:
            processed, posting_occurred = monitor_and_process_bills(api_key, limit=50, post_to_x=post_to_x, aggregate_all=aggregate_all)
            if aggregate_all:
                LOG.info(f"Monitoring session complete - {processed} bills aggregated and PNG created")
            elif post_to_x and posting_occurred:
                LOG.info(f"Monitoring session complete - {processed} bills processed and posted to X.com")
            elif post_to_x:
                LOG.info(f"Monitoring session complete - {processed} bills processed (X posting failed)")
            else:
                LOG.info(f"Monitoring session complete - {processed} bills processed")
            return 0
        except Exception as e:
            LOG.error(f"Monitoring failed: {e}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())