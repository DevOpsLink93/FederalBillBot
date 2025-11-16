#file servers an an example for users. 
import os

def store_api_key(api_key: str, filename: str = "congress_api_key.txt") -> None:

    with open(filename, "w") as f:
        f.write(api_key)

def get_api_key(filename: str = "congress_api_key.txt") -> str:
   # Read the API key from the specified file and return it. Example is stored in congress_api_key.txt.
   #You can get your own key from https://api.congress.gov/
    if not os.path.exists(filename):
        raise FileNotFoundError(f"{filename} does not exist.")
    with open(filename, "r") as f:
        return f.read().strip()