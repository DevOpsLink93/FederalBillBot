# Monitor Script: Continuously monitor congress.gov for newly introduced legislation

from __future__ import annotations

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

# Import XPoster for posting to X
try:
	from .x_poster import XPoster
except ImportError:
	from x_poster import XPoster

LOG = logging.getLogger("congress_monitor")


def format_bill_number(bill_type: str, bill_number: str) -> str:
	"""Format bill number in standard format (e.g., H.R. 1234, S. 56)."""
	if not bill_type or not bill_number:
		return bill_number or ""
	
	# Map bill types to standard format
	bill_type_map = {
		"HR": "H.R.",
		"S": "S.",
		"HRES": "H.Res.",
		"SRES": "S.Res.",
		"HJRES": "H.J.Res.",
		"SJRES": "S.J.Res.",
		"HCONRES": "H.Con.Res.",
		"SCONRES": "S.Con.Res."
	}
	
	formatted_type = bill_type_map.get(bill_type.upper(), bill_type)
	return f"{formatted_type} {bill_number}"


def construct_bill_url(congress: str, bill_type: str, bill_number: str) -> str:
	"""Construct congress.gov URL from bill data."""
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


def fetch_newly_introduced_bills(api_key: str, limit: int = 50) -> list:
	"""Fetch newly introduced bills from congress.gov API, sorted by introduced date."""
	url = "https://api.congress.gov/v3/bill"
	headers = {"X-Api-Key": api_key}
	# Sort by introducedDate descending to get most recently introduced bills
	params = {"sort": "introducedDate:desc", "limit": limit}
	
	try:
		response = requests.get(url, headers=headers, params=params)
		response.raise_for_status()
		data = response.json()
		
		if data.get("bills") and len(data["bills"]) > 0:
			return data["bills"]
		return []
	except Exception as e:
		LOG.error(f"Error fetching bills from API: {e}")
		return []


def get_bill_details(api_key: str, congress: str, bill_type: str, bill_number: str) -> dict:
	"""Get detailed bill information including sponsor and summary."""
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


def format_date_introduced(date_str: str) -> str:
	"""Format introduced date to YYYY-MM-DD format."""
	if not date_str:
		return "Unknown"
	try:
		dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
		return dt.strftime("%Y-%m-%d")
	except Exception:
		# Fallback: try to extract date portion
		return date_str[:10] if len(date_str) >= 10 else date_str


def process_new_bills(api_key: str, processed_bills: Set[str], poster: XPoster) -> int:
	"""Check for new bills and process them."""
	bills = fetch_newly_introduced_bills(api_key)
	if not bills:
		LOG.debug("No bills found from API")
		return 0
	
	new_count = 0
	
	for bill in bills:
		bill_type = bill.get("type", "")
		bill_number = bill.get("number", "")
		congress = bill.get("congress", "")
		
		# Create unique bill ID
		bill_id = f"{congress}-{bill_type}-{bill_number}"
		
		# Skip if already processed
		if bill_id in processed_bills:
			continue
		
		# Get bill details for sponsor and summary
		bill_detail = get_bill_details(api_key, congress, bill_type, bill_number)
		
		# Extract bill information
		formatted_bill_number = format_bill_number(bill_type, bill_number)
		date_introduced = format_date_introduced(bill.get("introducedDate", ""))
		sponsor = get_sponsor(bill_detail)
		summary = get_summary(bill_detail)
		link = construct_bill_url(congress, bill_type, bill_number)
		
		# Mark as processed
		processed_bills.add(bill_id)
		
		# Pass to X_poster
		LOG.info(f"New bill detected: {formatted_bill_number} - {date_introduced} - {sponsor}")
		poster.post_bill(formatted_bill_number, date_introduced, sponsor, summary, link)
		
		new_count += 1
	
	return new_count


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
	
	# Initialize XPoster
	poster = XPoster()
	
	# Track processed bills to avoid duplicates
	processed_bills: Set[str] = set()
	
	# Monitoring interval: 15 minutes = 900 seconds
	interval = 15 * 60
	
	LOG.info(f"Starting continuous monitoring for newly introduced legislation")
	LOG.info(f"Checking congress.gov API every {interval // 60} minutes")
	LOG.info("Press Ctrl+C to stop")
	
	try:
		while True:
			try:
				new_count = process_new_bills(api_key, processed_bills, poster)
				if new_count > 0:
					LOG.info(f"Processed {new_count} new bill(s)")
				else:
					LOG.debug("No new bills found")
				
				# Wait 15 minutes before next check
				LOG.debug(f"Waiting {interval // 60} minutes until next check...")
				time.sleep(interval)
				
			except Exception as e:
				LOG.exception("Error during bill processing, continuing...")
				# Continue monitoring even if there's an error
				time.sleep(interval)
				
	except KeyboardInterrupt:
		LOG.info("Monitoring interrupted by user; exiting")
		return 0


if __name__ == "__main__":
	raise SystemExit(main())



