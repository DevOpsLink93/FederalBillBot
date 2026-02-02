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


def get_dynamic_start_number(bill_type: str, fallback_start: int) -> int:
    """
    Dynamically determine the starting bill number for searching.
    Looks at the highest bill number in the database for the given type
    and adds a buffer to ensure we catch new bills.

    Args:
        bill_type: Bill type (e.g., "HR", "S", "HRES")
        fallback_start: Fallback starting number if database query fails

    Returns:
        Starting bill number for search
    """
    try:
        # Try to get the highest bill number from database
        conn = init_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT MAX(CAST(Bill_Number AS INTEGER))
            FROM bills
            WHERE Bill_Type = ? AND congress_id = 119
        """, (bill_type,))

        result = cursor.fetchone()
        conn.close()

        if result and result[0]:
            highest_db_bill = int(result[0])
            # Start 100 numbers higher than the highest in database to catch new bills
            # (Scans the next 100 bills in the House or Senate)
            dynamic_start = highest_db_bill + 100
            LOG.info(f"Using dynamic start for {bill_type} bills: {dynamic_start} (highest in DB: {highest_db_bill})")
            return dynamic_start
        else:
            LOG.info(f"No {bill_type} bills found in database, using fallback start: {fallback_start}")
            return fallback_start

    except Exception as e:
        LOG.warning(f"Could not determine dynamic start number for {bill_type}: {e}")
        LOG.info(f"Using fallback start: {fallback_start}")
        return fallback_start


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

    # Use a session for connection pooling
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key})

    try:
        LOG.info(f"Fetching bills from 119th Congress introduced between {from_date} and {today}...")

        all_bills = []

        # Check HR bills - start from known high numbers and work backwards more efficiently
        # Use a smarter approach: check for recent bills by starting high and stopping when we hit gaps
        hr_bills_found = 0
        consecutive_not_found = 0
        max_consecutive_not_found = 10  # Stop after this many consecutive missing bills

        LOG.info("Checking for recent HR bills...")

        # Dynamically find the highest HR bill number to start from
        # This ensures we always catch bills newer than what we've processed
        start_num = get_dynamic_start_number("HR", 7500)  # Fallback to 7500 to catch all new bills

        for bill_num in range(start_num, 6800, -1):  # Go from high to low
            bill_type = "hr"
            try:
                bill_detail = get_bill_details(api_key, "119", bill_type, str(bill_num), log_errors=False)
                if bill_detail:
                    # Get bill actions to find introduction date
                    actions = get_bill_actions(api_key, "119", bill_type, str(bill_num))
                    intro_action = find_introduction_action(actions)

                    if intro_action and intro_action.get("actionDate"):
                        introduced_date_str = intro_action.get("actionDate")
                        try:
                            introduced_date = datetime.fromisoformat(introduced_date_str.replace('Z', '+00:00')).date()
                            if from_date <= introduced_date <= today:
                                # Create bill data
                                bill = {
                                    "type": bill_type.upper(),
                                    "number": str(bill_num),
                                    "congress": "119",
                                    "title": bill_detail.get("title", "")
                                }
                                bill_data = extract_bill_data(bill, bill_detail, intro_action)
                                all_bills.append(bill_data)
                                hr_bills_found += 1
                                consecutive_not_found = 0  # Reset counter
                                LOG.debug(f"Found recent HR bill: {bill_type.upper()}.{bill_num} introduced on {introduced_date} (via {intro_action.get('type')} action)")
                            elif introduced_date < from_date:
                                # Bill is too old, we can stop going backwards
                                LOG.debug(f"Bill {bill_type.upper()}.{bill_num} is too old ({introduced_date}), stopping HR search")
                                break
                        except (ValueError, TypeError) as e:
                            LOG.debug(f"Could not parse date for {bill_type.upper()}.{bill_num}: {e}")
                    else:
                        # Bill has no intro action - log but continue searching (don't count against consecutive_not_found)
                        LOG.debug(f"Bill {bill_type.upper()}.{bill_num} has no IntroReferral action, continuing search")
                else:
                    # Bill details not found - this could be a bill that doesn't exist yet
                    # Don't count this as consecutive_not_found, just skip and continue
                    LOG.debug(f"Bill {bill_type.upper()}.{bill_num} not found (may not exist yet), continuing search")
                    continue
            except Exception as e:
                # Check if it's a 404 (bill doesn't exist) - this is expected when searching high numbers
                if "404" in str(e):
                    LOG.debug(f"Bill {bill_type.upper()}.{bill_num} does not exist (404), continuing search")
                    continue
                else:
                    # Other error - log as warning and count as consecutive not found
                    LOG.warning(f"Error checking HR bill {bill_num}: {e}")
                    consecutive_not_found += 1
                    if consecutive_not_found >= max_consecutive_not_found:
                        LOG.debug(f"Found {max_consecutive_not_found} consecutive errors, stopping HR search")
                        break

        # Check Senate bills (S.*) - use efficient search
        LOG.info("Checking Senate bills...")
        senate_bill_types = ["s", "sres", "sconres", "sjres"]

        for bill_type in senate_bill_types:
            senate_bills_found = 0
            consecutive_not_found = 0
            max_consecutive_not_found = 20

            # Different starting points for different bill types
            if bill_type == "s":
                start_num = get_dynamic_start_number("S", 500)  # Senate bills - increased fallback
            elif bill_type == "sres":
                start_num = get_dynamic_start_number("SRES", 300)  # Senate simple resolutions - increased fallback
            elif bill_type == "sjres":
                start_num = get_dynamic_start_number("SJRES", 300)  # Senate joint resolutions - increased fallback
            elif bill_type == "sconres":
                start_num = get_dynamic_start_number("SCONRES", 100)  # Senate concurrent resolutions - increased fallback
            else:
                start_num = 100   # Fallback

            for bill_num in range(start_num, 0, -1):
                try:
                    bill_detail = get_bill_details(api_key, "119", bill_type, str(bill_num), log_errors=False)
                    if bill_detail:
                        # Get bill actions to find introduction date
                        actions = get_bill_actions(api_key, "119", bill_type, str(bill_num))
                        intro_action = find_introduction_action(actions)

                        if intro_action and intro_action.get("actionDate"):
                            introduced_date_str = intro_action.get("actionDate")
                            try:
                                introduced_date = datetime.fromisoformat(introduced_date_str.replace('Z', '+00:00')).date()
                                if from_date <= introduced_date <= today:
                                    # Create bill data
                                    bill = {
                                        "type": bill_type.upper(),
                                        "number": str(bill_num),
                                        "congress": "119",
                                        "title": bill_detail.get("title", "")
                                    }
                                    bill_data = extract_bill_data(bill, bill_detail, intro_action)
                                    all_bills.append(bill_data)
                                    senate_bills_found += 1
                                    consecutive_not_found = 0
                                    LOG.debug(f"Found recent Senate bill: {bill_type.upper()}.{bill_num} introduced on {introduced_date} (via {intro_action.get('type')} action)")
                                elif introduced_date < from_date:
                                    # Too old, stop searching this type
                                    break
                            except (ValueError, TypeError) as e:
                                LOG.debug(f"Could not parse date for {bill_type.upper()}.{bill_num}: {e}")
                        else:
                            # Bill has no intro action - log but continue searching (don't count against consecutive_not_found)
                            LOG.debug(f"Bill {bill_type.upper()}.{bill_num} has no IntroReferral action, continuing search")
                    else:
                        # Bill details not found - this could be a bill that doesn't exist yet
                        # Don't count this as consecutive_not_found, just skip and continue
                        LOG.debug(f"Bill {bill_type.upper()}.{bill_num} not found (may not exist yet), continuing search")
                        continue
                except Exception as e:
                    # Check if it's a 404 (bill doesn't exist) - this is expected when searching high numbers
                    if "404" in str(e):
                        LOG.debug(f"Bill {bill_type.upper()}.{bill_num} does not exist (404), continuing search")
                        continue
                    else:
                        # Other error - log as warning and continue searching
                        LOG.warning(f"Error checking bill: {e}")
                        continue

        # Check other bill types (HJRES, HRES, HCONRES) - use efficient search
        LOG.info("Checking other bill types...")
        other_bill_types = ["hjres", "hres", "hconres"]

        for bill_type in other_bill_types:
            other_bills_found = 0
            consecutive_not_found = 0
            max_consecutive_not_found = 10

            # Use dynamic starting numbers for other bill types
            if bill_type == "hconres":
                start_num = get_dynamic_start_number("HCONRES", 200)  # Increased fallback
            elif bill_type == "hres":
                start_num = get_dynamic_start_number("HRES", 300)  # Increased fallback
            elif bill_type == "hjres":
                start_num = get_dynamic_start_number("HJRES", 300)  # Increased fallback
            else:
                start_num = 100  # Fallback

            for bill_num in range(start_num, 0, -1):
                try:
                    bill_detail = get_bill_details(api_key, "119", bill_type, str(bill_num), log_errors=False)
                    if bill_detail:
                        # Get bill actions to find introduction date
                        actions = get_bill_actions(api_key, "119", bill_type, str(bill_num))
                        intro_action = find_introduction_action(actions)

                        if intro_action and intro_action.get("actionDate"):
                            introduced_date_str = intro_action.get("actionDate")
                            try:
                                introduced_date = datetime.fromisoformat(introduced_date_str.replace('Z', '+00:00')).date()
                                if from_date <= introduced_date <= today:
                                    # Create bill data
                                    bill = {
                                        "type": bill_type.upper(),
                                        "number": str(bill_num),
                                        "congress": "119",
                                        "title": bill_detail.get("title", "")
                                    }
                                    bill_data = extract_bill_data(bill, bill_detail, intro_action)
                                    all_bills.append(bill_data)
                                    other_bills_found += 1
                                    consecutive_not_found = 0
                                    LOG.debug(f"Found recent {bill_type.upper()} bill: {bill_type.upper()}.{bill_num} introduced on {introduced_date} (via {intro_action.get('type')} action)")
                                elif introduced_date < from_date:
                                    # Too old, stop searching this type
                                    break
                            except (ValueError, TypeError) as e:
                                LOG.debug(f"Could not parse date for {bill_type.upper()}.{bill_num}: {e}")
                        else:
                            # Bill has no intro action - log but continue searching (don't count against consecutive_not_found)
                            LOG.debug(f"Bill {bill_type.upper()}.{bill_num} has no IntroReferral action, continuing search")
                    else:
                        # Bill details not found - this could be a bill that doesn't exist yet
                        # Don't count this as consecutive_not_found, just skip and continue
                        LOG.debug(f"Bill {bill_type.upper()}.{bill_num} not found (may not exist yet), continuing search")
                        continue
                except Exception as e:
                    # Check if it's a 404 (bill doesn't exist) - this is expected when searching high numbers
                    if "404" in str(e):
                        LOG.debug(f"Bill {bill_type.upper()}.{bill_num} does not exist (404), continuing search")
                        continue
                    else:
                        # Other error - log as warning and continue searching
                        LOG.warning(f"Error checking bill: {e}")
                        continue

        # Sort bills: HR bills first (descending by number), then other bills
        hr_bills = []
        other_bills = []

        for bill in all_bills:
            bill_type = bill.get("bill_type", "").upper()
            if bill_type == "HR":
                hr_bills.append(bill)
            else:
                other_bills.append(bill)

        # Sort HR bills by number descending
        try:
            hr_bills.sort(key=lambda b: int(b.get("bill_number", 0)), reverse=True)
        except (ValueError, TypeError):
            LOG.debug("Could not sort HR bills by number")

        # Sort other bills by type ascending, then numbers descending within each type
        try:
            other_bills.sort(key=lambda b: (b.get("bill_type", ""), -int(b.get("bill_number", 0))))
        except (ValueError, TypeError):
            LOG.debug("Could not sort other bills")

        # Combine sorted lists
        sorted_bills = hr_bills + other_bills

        # Limit to requested number
        bills_batch = sorted_bills[:limit]

        session.close()

        LOG.info(f"Successfully fetched {len(bills_batch)} bills introduced between {from_date} and {today}")
        return bills_batch

    except Exception as e:
        LOG.error(f"Error fetching bills from Congress API: {e}")
        session.close()
        return []


def get_bill_details(api_key: str, congress: str, bill_type: str, bill_number: str, log_errors: bool = True) -> Dict[str, Any]:
    """
    Get detailed bill information from Congress API.

    Args:
        api_key: Congress API key
        congress: Congress number (e.g., "119")
        bill_type: Bill type (e.g., "hr", "s")
        bill_number: Bill number
        log_errors: Whether to log errors as warnings (default True)

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
        if log_errors:
            LOG.warning(f"Error fetching bill details for {bill_type} {bill_number}: {e}")
        return {}


def get_bill_actions(api_key: str, congress: str, bill_type: str, bill_number: str) -> List[Dict[str, Any]]:
    """
    Get bill actions from Congress API to find introduction date.

    Args:
        api_key: Congress API key
        congress: Congress number (e.g., "119")
        bill_type: Bill type (e.g., "hr", "s")
        bill_number: Bill number

    Returns:
        List of bill actions
    """
    try:
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/actions"
        headers = {"X-Api-Key": api_key}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("actions", [])
    except Exception as e:
        LOG.warning(f"Error fetching bill actions for {bill_type} {bill_number}: {e}")
        return []


def find_introduction_action(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Find the bill introduction action from the list of actions.
    Prioritizes actions with Type: "IntroReferral" and official introduction codes:
    - House: Code "1000" (numeric), "1025" (resolutions), or "Intro-H" (alphabetic)
    - Senate: Code "10000" (numeric), "17000" (Senate resolutions), or "Intro-S" (alphabetic)
    Falls back to any "IntroReferral" action if specific codes aren't found.
    Returns the EARLIEST (oldest) matching action to get the actual introduction date.

    Args:
        actions: List of bill actions

    Returns:
        Introduction action dictionary or empty dict if not found
    """
    # Priority 1: Look for actions with Type="IntroReferral" AND specific introduction codes
    # Code 17000 is for Senate resolutions (SRES, SJRES, SCONRES)
    introduction_codes = ["1000", "10000", "1025", "17000", "Intro-H", "Intro-S"]
    priority_actions = []
    for action in actions:
        action_type = action.get("type", "")
        action_code = action.get("actionCode", "")
        if action_type == "IntroReferral" and action_code in introduction_codes:
            priority_actions.append(action)
    
    # Priority 1b: Also check for Floor actions with code 17000 (Senate resolutions)
    if not priority_actions:
        for action in actions:
            action_type = action.get("type", "")
            action_code = action.get("actionCode", "")
            if action_type == "Floor" and action_code == "17000":
                priority_actions.append(action)

    if priority_actions:
        # Sort by date (oldest first) and return the earliest
        try:
            priority_actions.sort(key=lambda x: x.get("actionDate", ""), reverse=False)
            return priority_actions[0]
        except:
            return priority_actions[0]

    # Priority 2: Look for any "IntroReferral" actions
    intro_referral_actions = []
    for action in actions:
        action_type = action.get("type", "")
        if action_type == "IntroReferral":
            intro_referral_actions.append(action)

    if intro_referral_actions:
        # Sort by date (oldest first) and return the earliest
        try:
            intro_referral_actions.sort(key=lambda x: x.get("actionDate", ""), reverse=False)
            return intro_referral_actions[0]
        except:
            return intro_referral_actions[0]

    # Fallback: Look for other introduction-related actions
    fallback_actions = []
    introduction_types = ["Introduced", "Introduction"]
    for action in actions:
        action_type = action.get("type", "")
        if action_type in introduction_types:
            fallback_actions.append(action)

    if fallback_actions:
        # Sort by date (oldest first) and return the earliest
        try:
            fallback_actions.sort(key=lambda x: x.get("actionDate", ""), reverse=False)
            return fallback_actions[0]
        except:
            return fallback_actions[0]

    # Final fallback: Look for actions that contain introduction-related keywords
    for action in actions:
        action_type = action.get("type", "").lower()
        description = action.get("text", "").lower()

        # Check for introduction-related keywords in type or description
        intro_keywords = ["intro", "introduced", "introduction", "refer"]
        if any(keyword in action_type or keyword in description for keyword in intro_keywords):
            return action

    return {}


def extract_bill_data(bill: Dict[str, Any], bill_detail: Dict[str, Any] = None, intro_action: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Extract and format bill data for processing.

    Args:
        bill: Basic bill data from API
        bill_detail: Detailed bill data (optional)
        intro_action: Introduction action data (optional)

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
    sponsor_party = "Unknown"
    summary = "Unknown"
    introduced_date = "Unknown"

    # Use introduction action date if available, otherwise fallback to bill_detail
    if intro_action and isinstance(intro_action, dict) and intro_action.get("actionDate"):
        introduced_date = intro_action.get("actionDate")
    elif bill_detail and isinstance(bill_detail, dict):
        introduced_date_str = bill_detail.get("introducedDate")
        if introduced_date_str:
            introduced_date = introduced_date_str

    if bill_detail and isinstance(bill_detail, dict):
        try:
            # Extract sponsor with party information
            sponsors = bill_detail.get("sponsors", [])
            if sponsors and isinstance(sponsors, list) and len(sponsors) > 0:
                sponsor_data = sponsors[0]  # Primary sponsor
                if isinstance(sponsor_data, dict):
                    first_name = sponsor_data.get("firstName", "")
                    last_name = sponsor_data.get("lastName", "")
                    title_prefix = sponsor_data.get("title", "")
                    state = sponsor_data.get("state", "")
                    party = sponsor_data.get("party", "")

                    if title_prefix and first_name and last_name:
                        sponsor = f"{title_prefix} {first_name} {last_name}"
                        if state:
                            sponsor += f" ({state}"
                            if party:
                                sponsor += f"-{party}"
                            sponsor += ")"
                        elif party:
                            sponsor += f" ({party})"
                    elif first_name and last_name:
                        sponsor = f"{first_name} {last_name}"
                        if state or party:
                            sponsor += " ("
                            if state:
                                sponsor += state
                            if state and party:
                                sponsor += "-"
                            if party:
                                sponsor += party
                            sponsor += ")"

                    # Store party separately for coloring
                    sponsor_party = party if party else "Unknown"

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
        'sponsor_party': sponsor_party,
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
    Separates bills by type (House vs Senate) and posts them as a thread.
    
    Threading logic:
    - House bills in main post (if any)
    - Senate bills in reply thread (if any and House bills exist)
    - Senate bills as main post (if no House bills)
    - Single post (if only House bills)
    - No post (if no bills)

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
    bills = fetch_recent_bills(api_key, limit=250, days_back=7)
    if not bills:
        LOG.warning("No bills fetched from API")
        return 0, False

    # Initialize XPoster for processing
    poster = XPoster()
    house_bills_to_process = []
    senate_bills_to_process = []

    # Collect and separate bills by type
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
        
        # Separate bills by chamber
        # House bills: HR, HRES, HJRES, HCONRES
        # Senate bills: S, SRES, SJRES, SCONRES
        if bill_type.startswith("H"):
            house_bills_to_process.append(bill_data)
        elif bill_type.startswith("S"):
            senate_bills_to_process.append(bill_data)

    # Process bills with threaded posting
    if house_bills_to_process or senate_bills_to_process:
        try:
            # Create timestamped filename base
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            png_filename_base = os.path.join(os.path.dirname(__file__), "..", "summary_images", f"fedbillsummary-{timestamp}.png")
            
            # Use threaded posting function
            processed_count, x_posting_successful = poster.post_bills_as_thread(
                house_bills=house_bills_to_process,
                senate_bills=senate_bills_to_process,
                post_to_x=post_to_x,
                create_png=True,
                png_filename_base=png_filename_base
            )
            posting_occurred = x_posting_successful
            
            if post_to_x:
                LOG.info(f"✅ Successfully processed {processed_count} bills into threaded posts and posted to X.com")
            else:
                LOG.info(f"✅ Successfully processed {processed_count} bills into PNG images and text records")
        except Exception as e:
            LOG.error(f"Failed to process bills with threading: {e}")
            return 0, False
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

    # Setup logging - use INFO level to show bill processing progress
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    # Also set the congress_monitor logger level
    logging.getLogger("congress_monitor").setLevel(logging.INFO)

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


def demonstrate_adaptive_search():
    """
    Demonstration function showing how the adaptive search works.
    This function shows how the system automatically adjusts to find new bills.
    """
    import sys
    sys.path.append('..')
    from api.congress_api import get_api_key

    # Get API key
    try:
        api_key_file = os.path.join("..", "api", "congress_api_key.txt")
        api_key = get_api_key(api_key_file)
    except Exception as e:
        print(f"Failed to load API key: {e}")
        return

    print("Adaptive Bill Search Demonstration")
    print("=" * 50)

    bill_types = ['HR', 'S', 'HRES', 'HCONRES', 'HJRES', 'SRES', 'SJRES', 'SCONRES']

    for bill_type in bill_types:
        # Get dynamic start number
        start_num = get_dynamic_start_number(bill_type, 1000)

        print(f"\n{bill_type} Bills:")
        print(f"  Database highest: {start_num - 50}")
        print(f"  Search starts at: {start_num}")
        print(f"  Buffer: +50 bills (catches new legislation)")

        # Quick check for bills in the range
        found_recent = 0
        for bill_num in range(start_num, start_num - 20, -1):  # Check last 20
            try:
                bill_detail = get_bill_details(api_key, "119", bill_type.lower(), str(bill_num), log_errors=False)
                if bill_detail:
                    found_recent += 1
            except:
                pass

        print(f"  Bills found in buffer range: {found_recent}")

    print("\nSystem automatically adapts to new bill numbers!")
    print("No more manual updates required.")


if __name__ == "__main__":
    # Allow demonstration mode
    if "--demo" in sys.argv:
        demonstrate_adaptive_search()
    else:
        raise SystemExit(main())