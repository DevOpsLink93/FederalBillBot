#Main Monitor Script. Detect new legislation items. Log To Database to avoid repeats. 

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional

import feedparser
import requests

import sqlite3

# Import XPoster for posting to X
try:
	from .x_poster import XPoster
except ImportError:
	from x_poster import XPoster

LOG = logging.getLogger("congress_monitor")


def load_seen(path: str) -> Dict[str, float]:
	if not os.path.exists(path):
		return {}
	try:
		with open(path, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception:
		LOG.exception("Failed to load seen file; starting with empty set")
		return {}


def save_seen(path: str, seen: Dict[str, float]) -> None:
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(seen, f, indent=2)
	os.replace(tmp, path)


def extract_doc_number(title: str) -> Optional[str]:
	# Common patterns: H.R. 1234, HR 1234, S. 56, S 56
	patterns = [r"\bH\.R\.\s*\d+\b", r"\bHR\s*\d+\b", r"\bH\s*\.\s*R\s*\d+\b",
				r"\bS\.\s*\d+\b", r"\bS\s*\d+\b"]
	for p in patterns:
		m = re.search(p, title, flags=re.IGNORECASE)
		if m:
			return m.group(0)
	return None


def fetch_feed(feed_url: str):
	# Using feedparser which handles RSS/Atom robustly
	LOG.debug("Fetching feed: %s", feed_url)
	return feedparser.parse(feed_url)


def build_tweet_text(docnum: Optional[str], title: str, link: str) -> str:
	if docnum:
		text = f"New legislation posted: {docnum} — {link}"
	else:
		# Fallback
		text = f"New legislation posted: {title} — {link}"
	# Ensure within X length limits (conservative, 270 chars)
	if len(text) > 270:
		text = text[:266] + "..."
	return text



# SQLite DB logic
def init_db(db_path: str):
	conn = sqlite3.connect(db_path)
	c = conn.cursor()
	c.execute('''CREATE TABLE IF NOT EXISTS posted_bills (
		id TEXT PRIMARY KEY,
		docnum TEXT,
		title TEXT,
		link TEXT,
		posted_at REAL
	)''')
	conn.commit()
	return conn

def bill_already_posted(conn, bill_id: str) -> bool:
	c = conn.cursor()
	c.execute("SELECT 1 FROM posted_bills WHERE id=?", (bill_id,))
	return c.fetchone() is not None

def log_new_bill(conn, bill_id: str, docnum: str, title: str, link: str):
	c = conn.cursor()
	c.execute("INSERT OR IGNORE INTO posted_bills (id, docnum, title, link, posted_at) VALUES (?, ?, ?, ?, ?)",
			  (bill_id, docnum, title, link, time.time()))
	conn.commit()




def process_feed(feed_url: str, db_path: str) -> int:
	conn = init_db(db_path)
	feed = fetch_feed(feed_url)
	if feed.bozo:
		LOG.warning("Feed parsing reported an error: %s", getattr(feed, "bozo_exception", None))

	new_count = 0
	entries = list(feed.entries)
	poster = XPoster()
	for entry in reversed(entries):
		entry_id = getattr(entry, "id", None) or getattr(entry, "guid", None) or entry.get("link")
		if not entry_id:
			entry_id = entry.get("link") or entry.get("title")
		if bill_already_posted(conn, entry_id):
			continue

		title = entry.get("title", "(no title)")
		link = entry.get("link", "")
		docnum = extract_doc_number(title)

		log_new_bill(conn, entry_id, docnum or "", title, link)
		LOG.info(f"Logged new bill: {docnum or title} — {link}")

		# Post to X using x_poster
		poster.post_bill(docnum or "", title, link)

		new_count += 1

	conn.close()
	return new_count



def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Monitor congress.gov RSS and log new items to SQLite DB")
	parser.add_argument("--feed", help="RSS/Atom feed URL to monitor",
						default=os.getenv("CONGRESS_FEED_URL", "https://www.congress.gov/rss"))
	parser.add_argument("--db", help="Path to SQLite database file", default="bills.db")
	parser.add_argument("--interval", help="Seconds between polls (default: 300)", type=int, default=300)
	parser.add_argument("--once", help="Run one check and exit", action="store_true")
	args = parser.parse_args(argv)

	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

	try:
		if args.once:
			count = process_feed(args.feed, args.db)
			LOG.info("Done. New items logged: %d", count)
			return 0

		LOG.info("Starting monitor loop; checking %s every %d seconds", args.feed, args.interval)
		while True:
			try:
				count = process_feed(args.feed, args.db)
				if count:
					LOG.info("Logged %d new items", count)
			except Exception:
				LOG.exception("Unhandled error during feed processing")
			time.sleep(args.interval)
	except KeyboardInterrupt:
		LOG.info("Interrupted by user; exiting")
		return 0


if __name__ == "__main__":
	raise SystemExit(main())

