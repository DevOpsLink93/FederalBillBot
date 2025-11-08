
# FederalBillBot

FederalBillBot is an automated bot that scans Congress.gov for new congressional legislation and logs each new bill.

## How it works

- The main script (`congress_x_post_processor/x_congress_monitor_main.py`) polls a Congress.gov RSS feed for new bills.
- When a new bill is detected, it is logged to a SQLite database (TBD).
- The script checks the database to avoid logging the same bill twice.
- All X (Twitter) posting logic is separated into `congress_x_post_processor/x_poster.py`.


## Notes

- The `api/` folder is ignored by git for local credentials.
- The Script is currently in dev and not functioning. 
