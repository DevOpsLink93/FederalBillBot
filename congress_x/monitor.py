#Author: DevOpsLink93 
# Monitor Script: Continuously monitor congress.gov for newly introduced legislation

from __future__ import annotations

#Import the necessary libraries for python script to run
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Set

import requests

# Import congress API key
try:
	from ..api.congress_api import get_api_key
except ImportError:
	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
	from api.congress_api import get_api_key

# Import Logging function to log the bills to the database
try:
	from ..sqlite.new_Legislation_log import process_and_log_bill
except ImportError:
	try:
		from sqlite.new_Legislation_log import process_and_log_bill
	except ImportError:
		# Fallback for different import paths
		import sqlite.new_Legislation_log
		process_and_log_bill = sqlite.new_Legislation_log.process_and_log_bill

# Import XPoster for posting to X
try:
	from .x_poster import XPoster
except ImportError:
	from x_poster import XPoster

LOG = logging.getLogger("congress_monitor")


#Bill Numbers that US Congress uses for bill identifier
def format_bill_number(bill_type: str, bill_number: str) -> str:
	"""Format bill number in standard format (e.g., H.R. 1234, S. 56)."""
	if not bill_type or not bill_number:
		return bill_number or ""
	
	# Map bill types to standard format
	bill_type_map = {
		"HR": "H.R.", #HR = House Resolution
		"S": "S.", #S = Senate Resolution
		"HRES": "H.Res.", #HRES = House Joint Resolution
		"SRES": "S.Res.", #SRES = Senate Joint Resolution
		"HJRES": "H.J.Res.", #HJRES = House Concurrent Resolution
		"SJRES": "S.J.Res.", #SJRES = Senate Concurrent Resolution
		"HCONRES": "H.Con.Res.", #HCONRES = House Concurrent Resolution
		"SCONRES": "S.Con.Res." #SCONRES = Senate Concurrent Resolution
	}
	
	formatted_type = bill_type_map.get(bill_type.upper(), bill_type)
	return f"{formatted_type} {bill_number}"

#Construct the URL for the bill to be posted to Social Media Platforms (currently just X)
def construct_bill_url(congress: str, bill_type: str, bill_number: str) -> str:
	
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
	
	bill_type_url = bill_type_map.get(bill_type.upper(), bill_type.lower())
	if congress and bill_type_url and bill_number:
		return f"https://www.congress.gov/bill/{congress}th-congress/{bill_type_url}/{bill_number}"
	return ""

#Fetch the latest 5 newly introduced bills from congress.gov API for the 119th Congress in the current year, sorted by introduced date.
def fetch_newly_introduced_bills(api_key: str, offset: int = 0) -> list:
#congress api available for full use
	url = "https://api.congress.gov/v3/bill"
	headers = {"X-Api-Key": api_key}
	# Sort by introducedDate descending to get most recently introduced bills
	current_year = datetime.now().year
	params = {
		"sort": "introducedDate:desc",
		"limit": 5,  # Always fetch exactly 5 bills
		"congress": 119,
		"introducedDate": f"{current_year}-01-01:{current_year}-12-31"
	}
	if offset > 0:
		params["offset"] = offset

	try:
		response = requests.get(url, headers=headers, params=params)
		response.raise_for_status()
		data = response.json()
		bills = data.get("bills", [])

		# Verify all bills are from the current Congress in current year
		verified_bills = []
		for bill in bills:
			congress_num = bill.get("congress")
			if congress_num != 119:
				continue
			verified_bills.append(bill)

		return verified_bills
	except Exception as e:
		LOG.debug(f"Error fetching bills from API: {e}")
		return []

#Get the detailed bill information including sponsor and summary from the congress.gov API anything that could not get retrieve will be unknown
def get_bill_details(api_key: str, congress: str, bill_type: str, bill_number: str) -> dict:
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


def get_sponsor(bill_detail: dict) -> str:
	"""Extract primary sponsor from bill detail."""
	sponsors = bill_detail.get("sponsors", [])
	if sponsors:
		sponsor = sponsors[0]
		first_name = sponsor.get("firstName", "")
		last_name = sponsor.get("lastName", "")
		title = sponsor.get("title", "")
		
		if title and first_name and last_name:
			return f"{title} {first_name} {last_name}"
		elif first_name and last_name:
			return f"{first_name} {last_name}"
	return "Unknown"


def get_summary(bill_detail: dict) -> str:
	"""Extract bill summary from bill detail."""
	summary = bill_detail.get("summary", {})
	if summary:
		summary_text = summary.get("text", "")
		if summary_text:
			return summary_text.strip()
	return "No summary available"


def is_bill_still_introduced(latest_action: dict) -> bool:
	"""Determine if a bill is still in the 'introduced' stage, ignoring committee referrals."""
	if not latest_action:
		return False

	action_text = latest_action.get("text", "").lower()

	# Bills that are still introduced include:
	# - Actions containing "introduced"
	# - Actions containing "referred to committee" (still considered introduced)
	# Bills that are NO LONGER introduced include:
	# - Actions containing "passed", "enacted", "signed", "became law", "vetoed", etc.

	# Check for actions that indicate the bill has progressed beyond introduction
	progressed_actions = [
		"passed", "enacted", "signed", "became law", "vetoed", "pocket vetoed",
		"presented to president", "cleared for white house", "to president",
		"failed of passage", "failed", "rejected", "defeated"
	]

	for progressed_action in progressed_actions:
		if progressed_action in action_text:
			return False

	# Check for actions that indicate the bill is still introduced
	introduced_actions = ["introduced", "referred to"]
	for introduced_action in introduced_actions:
		if introduced_action in action_text:
			return True

	# If we can't determine from the action text, assume it's not introduced
	return False

#chose the MMM-DD-YYYY format for the date usually matches the full text
def format_date_introduced(date_str: str) -> str:
	if not date_str:
		return "Unknown"
	try:
		dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))

		# Get the day with ordinal suffix
		day = dt.day
		if 11 <= day <= 13:
			suffix = "th"
		else:
			suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

		return dt.strftime(f"%B {day}{suffix} %Y")
	except Exception:
		# Fallback: try to extract date portion
		return date_str[:10] if len(date_str) >= 10 else date_str


def process_new_bills(api_key: str, processed_bills: Set[str], poster: XPoster) -> int:
    """
    Scan Congress.gov API for the latest 5 introduced bills (descending order),
    then process each for DB and X posting as before.
    """
    # Fetch only a single batch of the latest 5 bills for this scan/interval
    bills = fetch_newly_introduced_bills(api_key, offset=0)
    if not bills:
        return 0

    batch_new_count = 0  # Initialize counter for new bills processed

    # Process these 5 bills for possible DB insert / X posting
    for bill in bills:
        bill_type = bill.get("type", "").upper()
        bill_number = bill.get("number", "")
        congress = bill.get("congress", "")
        latest_action = bill.get("latestAction", {})

        # Check if bill is still introduced
        if not is_bill_still_introduced(latest_action):
            continue

        bill_id = f"{congress}-{bill_type}-{bill_number}"
        if bill_id in processed_bills:
            continue

        bill_detail = get_bill_details(api_key, congress, bill_type, bill_number)
        formatted_bill_number = format_bill_number(bill_type, bill_number)
        date_introduced = format_date_introduced(bill.get("introducedDate", ""))
        sponsor = get_sponsor(bill_detail)
        summary = get_summary(bill_detail)
        link = construct_bill_url(congress, bill_type, bill_number)
        bill_data = {
            'bill_number': bill_number,
            'bill_type': bill_type,
            'congress': congress,
            'title': bill.get("title", "Unknown"),
            'summary': summary,
            'sponsor': sponsor,
            'introduced_date': date_introduced,
            'url': link,
            'formatted_bill_number': formatted_bill_number
        }
        try:
            was_inserted = process_and_log_bill(bill_data)
            if was_inserted:
                batch_new_count += 1
                print(f"📢 New bill found: {formatted_bill_number}")
                try:
                    poster.post_bill(
                        formatted_bill_number,
                        date_introduced,
                        sponsor,
                        summary,
                        link
                    )
                    print(f"✅ Posted to X: {formatted_bill_number}")
                except Exception as e:
                    print(f"❌ Failed to post to X: {formatted_bill_number}")
        except Exception as e:
            LOG.error(f"Database operation failed for bill {formatted_bill_number}: {e}")
            LOG.error("Stopping script due to database error")
            raise
        processed_bills.add(bill_id)

    return batch_new_count


def countdown_timer(seconds: int) -> None:
	"""Display a countdown timer with minutes and seconds remaining."""
	for remaining in range(seconds, 0, -1):
		mins, secs = divmod(remaining, 60)
		timer_display = f"\rNext scan in {mins:02d}:{secs:02d}"
		print(timer_display, end='', flush=True)
		time.sleep(1)
	print("\r" + " " * 25 + "\r", end='', flush=True)  # Clear the timer line


def perform_bulk_load(api_key: str, poster: XPoster) -> None:
	"""Perform initial bulk load of recent bills Congress in current year into database and post to X."""
	current_year = datetime.now().year
	LOG.info(f"🚀 Starting bulk load of recent bills ({current_year})...")

	total_processed = 0
	offset = 0
	batch_size = 5

	while True:
		batch_num = offset // batch_size + 1
		LOG.info(f"📦 Fetching batch {batch_num} (latest 5 bills, offset: {offset})")

		bills = fetch_newly_introduced_bills(api_key, offset=offset)
		if not bills:
			LOG.info("📦 No more bills found, bulk load complete")
			break

		current_year = datetime.now().year
		LOG.info(f"📦 Processing {len(bills)} bills from Congress ({current_year}) in batch {batch_num}...")
		batch_new_count = 0
		batch_existing_count = 0

		for bill in bills:
			bill_type = bill.get("type", "")
			bill_number = bill.get("number", "")
			congress = bill.get("congress", "")

			# Check if this bill is still in the "introduced" stage
			latest_action = bill.get("latestAction", {})
			if not is_bill_still_introduced(latest_action):
				action_text = latest_action.get("text", "No action") if latest_action else "No action"
				LOG.debug(f"⏭️  Skipping bill {bill_type}.{bill_number} - no longer introduced (latest action: '{action_text}')")
				continue

			# Get bill details for sponsor and summary
			bill_detail = get_bill_details(api_key, congress, bill_type, bill_number)

			# Extract bill information
			formatted_bill_number = format_bill_number(bill_type, bill_number)
			date_introduced = format_date_introduced(bill.get("introducedDate", ""))
			sponsor = get_sponsor(bill_detail)
			summary = get_summary(bill_detail)
			link = construct_bill_url(congress, bill_type, bill_number)

			# Prepare bill data for database processing
			bill_data = {
				'bill_number': bill_number,
				'bill_type': bill_type,
				'congress': congress,
				'title': bill.get("title", "Unknown"),
				'summary': summary,
				'sponsor': sponsor,
				'introduced_date': date_introduced,
				'url': link,
				'formatted_bill_number': formatted_bill_number
			}

			# STEP 1: Verify against database and insert if new
			try:
				was_inserted = process_and_log_bill(bill_data)
				if was_inserted:
					LOG.info(f"✓ New introduced bill inserted into database: {formatted_bill_number}")
					batch_new_count += 1

					# STEP 2: Post to X.com immediately after successful database insert
					try:
						poster.post_bill(
							formatted_bill_number,
							date_introduced,
							sponsor,
							summary,
							link
						)
						LOG.info(f"✅ Successfully posted introduced bill to X: {formatted_bill_number}")
					except Exception as e:
						LOG.error(f"❌ Failed to post bill to X: {formatted_bill_number} - {e}")
				else:
					batch_existing_count += 1
					LOG.debug(f"⏭️  Bill {formatted_bill_number} already exists in database, skipping")
			except Exception as e:
				LOG.error(f"❌ Database operation failed for bill {formatted_bill_number}: {e}")
				LOG.error("🛑 Stopping bulk load due to database error")
				raise

		total_processed += len(bills)
		LOG.info(f"📦 Batch complete: {batch_new_count} new bills inserted, {batch_existing_count} already existed")

		# If we found existing bills in this batch, we've caught up - stop bulk loading
		if batch_existing_count > 0:
			LOG.info(f"📦 Found {batch_existing_count} existing bills in this batch, bulk load complete")
			break

		# Move to next batch
		offset += batch_size

		# Small delay between batches to be respectful to the API
		time.sleep(1)

	LOG.info(f"🚀 Bulk load complete! Processed {total_processed} total bills")


def main() -> int:
	"""Main monitoring loop."""
	# Setup logging
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(message)s"
	)
	
	# Get API key
	api_key_file = os.path.join(
		os.path.dirname(__file__),
		"..",
		"api",
		"congress_api_key.txt"
	)
	
	try:
		api_key = get_api_key(api_key_file)
		LOG.info("Successfully loaded congress.gov API key")
	except Exception as e:
		LOG.error(f"Failed to load API key from {api_key_file}: {e}")
		return 1

	# Initialize XPoster for posting
	poster = XPoster()

	# STEP 1: Perform initial bulk load of recent bills from 119th Congress (current year)
	try:
		perform_bulk_load(api_key, poster)
		LOG.info("✅ Bulk load completed successfully")
	except Exception as e:
		LOG.error(f"❌ Bulk load failed: {e}")
		return 1

	# STEP 2: Start continuous monitoring
	# Track processed bills to avoid duplicates in this session
	processed_bills: Set[str] = set()

	# Monitoring interval: 15 minutes = 900 seconds
	interval = 15 * 60

	print("🔄 Starting continuous monitoring for newly introduced legislation")
	print("Checking congress.gov API every 15 minutes")
	print("Press Ctrl+C to stop")
	print()

	try:
		while True:
			try:
				# Check for new bills
				new_count = process_new_bills(api_key, processed_bills, poster)

				if new_count > 0:
					print(f"📢 Processed {new_count} new bill(s)")
				else:
					print("🔍 Scan complete - no new legislation found")

				print("Will recheck in 15 minutes...")
				countdown_timer(interval)

			except Exception as e:
				print(f"❌ Monitoring error: {e}")
				print("Will retry in 15 minutes...")
				countdown_timer(interval)

	except KeyboardInterrupt:
		print("\nMonitoring stopped by user")
		return 0


if __name__ == "__main__":
	raise SystemExit(main())



