# Get Most Recent Bill from congress.gov API

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional
from pathlib import Path
from datetime import datetime

import requests

# Import congress API key
try:
	from ..api.congress_api import get_api_key
except ImportError:
	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
	from api.congress_api import get_api_key

# Import bill_logging for database operations (COMMENTED OUT)
# try:
# 	from ..sqlite.bill_logging import init_db, log_new_bill
# except ImportError:
# 	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 	from sqlite.bill_logging import init_db, log_new_bill

# Import x_poster for posting to X
try:
	from .x_poster import post_bill_to_x
except ImportError:
	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
	from congress_x_post_processor.x_poster import post_bill_to_x

LOG = logging.getLogger("get_most_recent_bill")


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


def get_sponsor_from_bill(api_key: str, congress: str, bill_type: str, bill_number: str) -> str:
	"""Get the primary sponsor from a bill's detail endpoint."""
	try:
		url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}"
		headers = {"X-Api-Key": api_key}
		response = requests.get(url, headers=headers)
		response.raise_for_status()
		data = response.json()
		
		bill = data.get("bill", {})
		sponsors = bill.get("sponsors", [])
		
		if sponsors:
			# Get the first sponsor (primary sponsor)
			sponsor = sponsors[0]
			# Get the name without party affiliation
			first_name = sponsor.get("firstName", "")
			last_name = sponsor.get("lastName", "")
			title = sponsor.get("title", "")
			
			# Format: "Rep. John Doe" or "Sen. Jane Smith"
			if title and first_name and last_name:
				return f"{title} {first_name} {last_name}"
			elif first_name and last_name:
				return f"{first_name} {last_name}"
		
		return "Unknown"
	except Exception as e:
		LOG.warning(f"Error fetching sponsor for {bill_type} {bill_number}: {e}")
		return "Unknown"


def get_most_recent_bill(api_key: str) -> Optional[dict]:
	"""Get the most recent bill from congress.gov API."""
	url = "https://api.congress.gov/v3/bill"
	headers = {"X-Api-Key": api_key}
	# Sort by introduced date descending to get most recent
	params = {"sort": "updateDate:desc", "limit": 1}
	
	try:
		response = requests.get(url, headers=headers, params=params)
		response.raise_for_status()
		data = response.json()
		
		if data.get("bills") and len(data["bills"]) > 0:
			return data["bills"][0]
		return None
	except Exception as e:
		LOG.error(f"Error fetching most recent bill: {e}")
		return None


def extract_bill_info(bill_data: dict, api_key: str) -> Optional[dict]:
	"""Extract bill number, date introduced, and sponsor from bill data."""
	if not bill_data:
		return None
	
	bill_type = bill_data.get("type", "")
	bill_number = bill_data.get("number", "")
	congress = bill_data.get("congress", "")
	
	# Format bill number (e.g., "H.R. 1234")
	formatted_bill_number = format_bill_number(bill_type, bill_number)
	
	# Get introduced date
	introduced_date = bill_data.get("introducedDate", "")
	if introduced_date:
		# Parse and format date to YYYY-MM-DD
		try:
			dt = datetime.fromisoformat(introduced_date.replace('Z', '+00:00'))
			date_introduced = dt.strftime("%Y-%m-%d")
		except Exception:
			# Fallback if date parsing fails
			date_introduced = introduced_date[:10] if len(introduced_date) >= 10 else datetime.now().strftime("%Y-%m-%d")
	else:
		date_introduced = datetime.now().strftime("%Y-%m-%d")
	
	# Get sponsor from bill detail endpoint
	sponsor = get_sponsor_from_bill(api_key, congress, bill_type, bill_number)
	
	return {
		"bill_number": formatted_bill_number,
		"date_introduced": date_introduced,
		"sponsor": sponsor
	}


def process_most_recent_bill() -> bool:
	"""Get the most recent bill and post it to X."""
	# Get API key
	try:
		key_path = os.path.join(os.path.dirname(__file__), '..', 'api', 'congress_api_key.txt')
		api_key = get_api_key(key_path)
	except Exception as e:
		LOG.error(f"Error getting API key: {e}")
		return False
	
	# Get most recent bill
	bill_data = get_most_recent_bill(api_key)
	if not bill_data:
		LOG.warning("No bills found")
		return False
	
	# Extract bill information
	bill_info = extract_bill_info(bill_data, api_key)
	if not bill_info:
		LOG.warning("Could not extract bill information")
		return False
	
	# COMMENTED OUT: Database logging
	# Initialize database connection
	# conn = init_db(db_path)
	# 
	# # Log to database (will handle X posting if new)
	# is_new = log_new_bill(
	# 	conn,
	# 	bill_info["bill_number"],
	# 	bill_info["date_introduced"],
	# 	bill_info["sponsor"]
	# )
	# 
	# conn.close()
	# 
	# if is_new:
	# 	LOG.info(f"New bill processed: {bill_info['bill_number']} - {bill_info['date_introduced']} - {bill_info['sponsor']}")
	# else:
	# 	LOG.info(f"Bill already exists: {bill_info['bill_number']}")
	# 
	# return is_new
	
	# Post directly to X
	LOG.info(f"Posting bill to X: {bill_info['bill_number']} - {bill_info['date_introduced']} - {bill_info['sponsor']}")
	post_bill_to_x(
		bill_info["bill_number"],
		bill_info["date_introduced"],
		bill_info["sponsor"]
	)
	
	return True


def main(argv: Optional[list] = None) -> int:
	parser = argparse.ArgumentParser(description="Get most recent bill from congress.gov API and post to X")
	# COMMENTED OUT: Database argument no longer needed
	# parser.add_argument("--db", help="Path to SQLite database file", 
	# 					default=os.path.join(os.path.dirname(__file__), "..", "sqlite", "fedbillalertdb.db"))
	args = parser.parse_args(argv)
	
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	
	try:
		# COMMENTED OUT: Database path no longer needed
		# db_path = os.path.abspath(args.db)
		LOG.info(f"Processing most recent bill from congress.gov API")
		# LOG.info(f"Database path: {db_path}")
		
		success = process_most_recent_bill()
		
		if success:
			LOG.info("Most recent bill has been posted to X")
		else:
			LOG.info("Failed to process most recent bill")
		
		return 0
	except Exception as e:
		LOG.exception("Unhandled error")
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
