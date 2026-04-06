from pprint import pprint

import requests
from bs4 import BeautifulSoup


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


def find_videos(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    # 1. Look for <video> tags
    videos = [tag["src"] for tag in soup.find_all("video") if tag.has_attr("src")]

    # 2. Look for <source> tags (common inside <video>)
    sources = [tag["src"] for tag in soup.find_all("source") if tag.has_attr("src")]

    # 3. Look for <iframe> tags (used by YouTube/Vimeo)
    iframes = [tag["src"] for tag in soup.find_all("iframe") if tag.has_attr("src")]

    return videos + sources + iframes


hi = input("Enter URL (e.g., api.github.com): ")
result = curlThis(hi)

if result:
    pprint(result)
