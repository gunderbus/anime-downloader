import random
import time
from pprint import pprint

import requests
from bs4 import BeautifulSoup

# --- CONFIG ---
pathtrue = ""


def download_video(url, filename):
    # Ensure filename has an extension
    if not filename.endswith(".mp4"):
        filename += ".mp4"

    print(f"Starting download: {url}")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"Finished downloading {filename}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")


def find_videos(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        # We use a set to avoid duplicate links
        found = set()

        # Check <video>, <source>, and <iframe>
        for tag in soup.find_all(["video", "source", "iframe"]):
            src = tag.get("src")
            if src:
                # Handle relative URLs (e.g., /video.mp4 -> https://site.com/video.mp4)
                if src.startswith("/"):
                    from urllib.parse import urljoin

                    src = urljoin(url, src)
                found.add(src)

        return list(found)
    except:
        return []


def downloadPage(url):
    # find_videos now returns a list of all types of video links
    links = find_videos(url)

    if not links:
        print("No video links found on this page.")
        return

    # FIX: You can't pass a LIST to download_video, you must pick one or loop
    for link in links:
        # Create a unique filename
        # time.time() is better for simple timestamps than clock_gettime
        timestamp = int(time.time())
        rand_id = random.randint(1000, 9999)
        name = f"Anime_Download_{timestamp}_{rand_id}"

        download_video(link, name)


# --- EXECUTION ---
hi = input("Enter URL to scan for videos: ")
if not hi.startswith("http"):
    hi = "https://" + hi

downloadPage(hi)
