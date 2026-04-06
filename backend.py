import random
import time
from urllib.parse import urljoin

import requests
import yt_dlp
from bs4 import BeautifulSoup


def download_with_ytdlp(url):
    """
    Handles both direct MP4s and M3U8 playlists.
    It automatically stitches segments together.
    """
    timestamp = int(time.time())
    rand_id = random.randint(1000, 9999)

    ydl_opts = {
        # 'best' ensures it grabs the highest quality available
        "format": "best",
        # Filename format: Anime_Download_TIMESTAMP_ID.extension
        "outtmpl": f"Anime_Download_{timestamp}_{rand_id}.%(ext)s",
        "quiet": False,  # Set to True if you want less text in the terminal
        "no_warnings": True,
    }

    print(f"--- Attempting download: {url} ---")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Could not download {url}: {e}")


def find_all_media(url):
    """Scans for video tags, sources, iframes, and raw links."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        found = set()

        # 1. Look for tags that usually have video sources
        for tag in soup.find_all(["video", "source", "iframe", "a"]):
            src = tag.get("src") or tag.get("href")

            if src:
                full_url = urljoin(url, src)
                # Filter for video-related extensions
                if any(
                    ext in full_url.lower()
                    for ext in [".mp4", ".m3u8", ".webm", ".mkv"]
                ):
                    found.add(full_url)

        return list(found)
    except Exception as e:
        print(f"Error scanning page: {e}")
        return []


def start_scraper(target_url):
    if not target_url.startswith("http"):
        target_url = "https://" + target_url

    print(f"Scanning {target_url}...")
    links = find_all_media(target_url)

    if not links:
        print("No video or m3u8 links detected.")
        return

    print(f"Found {len(links)} potential links. Starting downloads...")
    for link in links:
        download_with_ytdlp(link)


# --- Run ---
user_url = input("Enter the URL to scrape: ")
start_scraper(user_url)
