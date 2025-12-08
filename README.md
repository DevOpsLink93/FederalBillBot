
# FederalBillBot

FederalBillBot is an automated bot that scans Congress.gov for new congressional legislation and logs each new bill every 15 minutes. Currently just scans for a new legislation that has been introduced. 

## How it works

- The script (`congress_x_/monitor.py`) polls a Congress.gov RSS feed for new bills.
- When a new bill is detected, it is logged to a SQLite database.
- The script checks the database to avoid logging the same bill twice.
- All X posting logic is separated into `congress_x/x_poster.py`.


## Notes

- The `api/` and `sqlite` folder is ignored by git based upon the security of local credentials
- The Script is currently in dev posting to X, all post until this read me are current post test. 

