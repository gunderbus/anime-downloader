from pprint import pprint

import requests


def curlThis(url: str):
    # It's good practice to add 'https://' if the user forgets it
    if not url.startswith("http"):
        url = "https://" + url

    try:
        response = requests.get(url)
        diddy = response.status_code

        # FIX 1: Use 'and' instead of 'or'
        # Your old code: if > 199 or < 299 was ALWAYS true (because 500 is > 199)
        if 200 <= diddy <= 299:
            print("Worked")
            print("Status code: " + str(diddy))

            # FIX 2: Added parentheses () to call the method
            return response.json()
        else:
            print(f"Error: Received status code {diddy}")
            return None

    except Exception as e:
        print(f"Connection failed: {e}")
        return None


hi = input("Enter URL (e.g., api.github.com): ")
result = curlThis(hi)

if result:
    pprint(result)
