#Main Monitor Script. Detect new legislation items. 

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from typing import List, Optional
from datetime import datetime

import feedparser

# Import bill_logging for database operations, TBD for alpha v.02
try:
	from ..sqlite.bill_logging import init_db, log_new_bill
except ImportError:
	import sys
	from pathlib import Path
	sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
	from sqlite.bill_logging import init_db, log_new_bill

LOG = logging.getLogger("congress_monitor")


def extract_doc_number(title: str) -> Optional[str]:
	# Common patterns: H.R. 1234, HR 1234, S. 56, S 56
	patterns = [r"\bH\.R\.\s*\d+\b", r"\bHR\s*\d+\b", r"\bH\s*\.\s*R\s*\d+\b",
				r"\bS\.\s*\d+\b", r"\bS\s*\d+\b"]
	for p in patterns:
		m = re.search(p, title, flags=re.IGNORECASE)
		if m:
			return m.group(0)
	return None


def get_congressional_cycle(date_str: str) -> int:
	"""Calculate congressional cycle from date. Congress cycles are 2 years starting in odd years."""
	try:
		dt = datetime.strptime(date_str, "%Y-%m-%d")
		year = dt.year
		# Congressional cycles: 1st Congress was 1789-1790
		# Formula: ((year - 1789) // 2) + 1, but adjusted for modern cycles
		# Modern formula: Congress number = ((year - 1789) // 2) + 1
		# For years 2023-2024 = 118th, 2025-2026 = 119th, etc.
		congress = ((year - 1789) // 2) + 1
		return congress
	except Exception:
		# Fallback: calculate from current date
		year = datetime.now().year
		return ((year - 1789) // 2) + 1


def extract_date_introduced(entry) -> str:
	"""Extract date introduced from RSS feed entry."""
	# Try published date first
	if hasattr(entry, 'published_parsed') and entry.published_parsed:
		try:
			dt = datetime(*entry.published_parsed[:6])
			return dt.strftime("%Y-%m-%d")
		except Exception:
			pass
	
	# Try published field
	if hasattr(entry, 'published') or 'published' in entry:
		pub_date = getattr(entry, 'published', None) or entry.get('published', '')
		if pub_date:
			try:
				# Try parsing common date formats
				dt = feedparser._parse_date(pub_date)
				if dt:
					return dt.strftime("%Y-%m-%d")
			except Exception:
				pass
	
	# Fallback to current date
	return datetime.now().strftime("%Y-%m-%d")


def extract_sponsor(entry) -> str:
	"""Extract sponsor from RSS feed entry description or title."""
	# Try to extract from description
	description = getattr(entry, 'description', None) or entry.get('description', '')
	if description:
		# Look for common sponsor patterns in description
		# Patterns like "Introduced by Rep. John Doe" or "Sponsor: Sen. Jane Smith"
		sponsor_patterns = [
			r"Introduced by\s+([^\.]+)",
			r"Sponsor[:\s]+([^\.]+)",
			r"by\s+(Rep\.|Sen\.)\s+([^\.]+)",
		]
		for pattern in sponsor_patterns:
			m = re.search(pattern, description, re.IGNORECASE)
			if m:
				sponsor = m.group(1) if len(m.groups()) == 1 else m.group(0)
				return sponsor.strip()
	
	# Try to extract from title
	title = getattr(entry, 'title', None) or entry.get('title', '')
	if title:
		# Look for sponsor in title patterns
		sponsor_patterns = [
			r"by\s+(Rep\.|Sen\.)\s+([^\-]+)",
		]
		for pattern in sponsor_patterns:
			m = re.search(pattern, title, re.IGNORECASE)
			if m:
				sponsor = m.group(0)
				return sponsor.strip()
	
	# Fallback
	return "Unknown"


def fetch_feed(feed_url: str):
	# Using feedparser which handles RSS
	LOG.debug("Fetching feed: %s", feed_url)
	return feedparser.parse(feed_url)




def process_feed(feed_url: str, db_path: str) -> int:
	# COMMENTED OUT: Database connection
	# conn = init_db(db_path)
	feed = fetch_feed(feed_url)
	if feed.bozo:
		LOG.warning("Feed parsing reported an error: %s", getattr(feed, "bozo_exception", None))

	new_count = 0
	entries = list(feed.entries)
	
	for entry in reversed(entries):
		title = getattr(entry, "title", None) or entry.get("title", "(no title)")
		bill_number = extract_doc_number(title)
		
		if not bill_number:
			LOG.debug(f"Skipping entry without bill number: {title}")
			continue
		
		# Extract date_introduced and sponsor
		date_introduced = extract_date_introduced(entry)
		sponsor = extract_sponsor(entry)
		
		# Calculate congressional cycle from date introduced
		congressional_cycle = get_congressional_cycle(date_introduced)
		
		# COMMENTED OUT: Database logging
		# Pass to bill_logging (will handle database logging and X posting)
		# is_new = log_new_bill(conn, bill_number, date_introduced, sponsor, congressional_cycle)
		# 
		# if is_new:
		# 	LOG.info(f"New bill detected: {bill_number} - {date_introduced} - {sponsor}")
		# 	new_count += 1
		# else:
		# 	LOG.debug(f"Bill {bill_number} already exists, skipping")
		
		# Found 1 bill, log it and exit
		LOG.info(f"Bill found: {bill_number} - {date_introduced} - {sponsor} (Congress {congressional_cycle})")
		new_count = 1
		break  # Exit after finding 1 bill

	# COMMENTED OUT: Database connection close
	# conn.close()
	return new_count


#RSS feed
def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Monitor congress.gov RSS and log new items to SQLite DB")
	parser.add_argument("--feed", help="RSS/Atom feed URL to monitor",
						default=os.getenv("CONGRESS_FEED_URL", "https://www.congress.gov/rss"))
	parser.add_argument("--db", help="Path to SQLite database file", default="bills.db")
	parser.add_argument("--interval", help="Seconds between polls (default: 1800 = 30 minutes)", type=int, default=1800)
	parser.add_argument("--once", help="Run one check and exit", action="store_true")
	args = parser.parse_args(argv)

	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

	try:
		# Process feed once and exit after finding 1 bill
		count = process_feed(args.feed, args.db)
		LOG.info("Done. Found %d bill(s). Exiting.", count)
		return 0

		# COMMENTED OUT: Continuous monitoring loop
		# if args.once:
		# 	count = process_feed(args.feed, args.db)
		# 	LOG.info("Done. New items logged: %d", count)
		# 	return 0
		# 
		# LOG.info("Starting monitor loop; checking %s every %d seconds", args.feed, args.interval)
		# while True:
		# 	try:
		# 		count = process_feed(args.feed, args.db)
		# 		if count:
		# 			LOG.info("Logged %d new items", count)
		# 	except Exception:
		# 		LOG.exception("Unhandled error during feed processing")
		# 	time.sleep(args.interval)
	except KeyboardInterrupt:
		LOG.info("Interrupted by user; exiting")
		return 0


if __name__ == "__main__":
	raise SystemExit(main())

