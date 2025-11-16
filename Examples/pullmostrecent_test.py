#Example of a simple print of most recent bill from congress.gov
from api.congress_api import get_api_key
import requests
import os

def get_most_recent_bill():
	url = "https://api.congress.gov/v3/bill"
	key_path = os.path.join(os.path.dirname(__file__), '..', 'api', 'congress_api_key.txt')
	api_key = get_api_key(key_path)
	headers = {"X-Api-Key": api_key}
	params = {"sort": "latestAction.actionDate:desc", "limit": 1}
	response = requests.get(url, headers=headers, params=params)
	response.raise_for_status()
	data = response.json()
	if data.get("bills"):
		bill = data["bills"][0]
		bill_type = bill.get("type", "")
		bill_number = bill.get("number", "")
		congress = bill.get("congress", "")
		combined_number = f"{bill_type}.{bill_number}" if bill_type and bill_number else bill_number
		bill_heading = bill.get("title", "")
		# Construct direct congress.gov URL
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
			direct_url = f"https://www.congress.gov/bill/{congress}th-congress/{bill_type_url}/{bill_number}"
		else:
			direct_url = "(URL unavailable)"
		print(f"Most recent bill: {combined_number}")
		print(f"Bill URL: {direct_url}")
		print(f"Bill heading: {bill_heading}")
	else:
		print("No bills found.")

if __name__ == "__main__":
	get_most_recent_bill()