
# Post new congressional legislation to X
from api.x_api_call import get_x_api_client

#Variables passed from main monitor script. Current Posting to X:
#Date Introduced in YYYY-MM-DD format
#Sponsor Name. Not highlighting party affiliation.
#Congressional Cycle (e.g., 119)
def construct_bill_url(bill_number: str, congressional_cycle: int) -> str:
    """Construct congress.gov URL from bill number and congressional cycle."""
    import re
    
    # Parse bill number to extract type and number
    # Patterns: H.R. 1234, S. 56, H.Res. 123, etc.
    patterns = [
        (r"H\.R\.\s*(\d+)", "house-bill"),
        (r"S\.\s*(\d+)", "senate-bill"),
        (r"H\.Res\.\s*(\d+)", "house-resolution"),
        (r"S\.Res\.\s*(\d+)", "senate-resolution"),
        (r"H\.J\.Res\.\s*(\d+)", "house-joint-resolution"),
        (r"S\.J\.Res\.\s*(\d+)", "senate-joint-resolution"),
        (r"H\.Con\.Res\.\s*(\d+)", "house-concurrent-resolution"),
        (r"S\.Con\.Res\.\s*(\d+)", "senate-concurrent-resolution"),
        (r"HR\s*(\d+)", "house-bill"),
        (r"S\s*(\d+)", "senate-bill"),
    ]
    
    bill_number_clean = bill_number.strip()
    for pattern, bill_type in patterns:
        match = re.search(pattern, bill_number_clean, re.IGNORECASE)
        if match:
            number = match.group(1)
            return f"https://www.congress.gov/bill/{congressional_cycle}th-congress/{bill_type}/{number}"
    
    # Fallback: try to extract just the number
    number_match = re.search(r"(\d+)", bill_number_clean)
    if number_match:
        number = number_match.group(1)
        # Default to house-bill if we can't determine type
        return f"https://www.congress.gov/bill/{congressional_cycle}th-congress/house-bill/{number}"
    
    return ""

#Post the bill to x
def post_bill_to_x(bill_number, date_introduced, sponsor, congressional_cycle):
    # Print bill details
    print(f"Bill Number: {bill_number}")
    print(f"Date Introduced: {date_introduced}")
    print(f"Sponsor: {sponsor}")
    print(f"Congressional Cycle: {congressional_cycle}")
    
    # Congress.gov bill URL
    bill_url = construct_bill_url(bill_number, congressional_cycle)
    
    # Create message for X post with URL
    if bill_url:
        message = f"Bill Number: {bill_number}\nDate Introduced: {date_introduced}\nSponsor: {sponsor}\n{bill_url}"
    else:
        message = f"Bill Number: {bill_number}\nDate Introduced: {date_introduced}\nSponsor: {sponsor}"
    
    try:
        client = get_x_api_client()
        response = client.create_tweet(text=message)
        print(f"Post to X successful! X ID: {response.data['id']}")
    except Exception as e:
        print(f"Post to X failed: {e}")

#Comment out use only in test purposes. 
# Example usage (replace with real data from congress.gov)
# if __name__ == "__main__":
#     bill_number = "H.R.1234"
#     date_introduced = "2025-11-16"
#     sponsor = "Rep. Jane Doe"
#     post_bill_to_x(bill_number, date_introduced, sponsor)
