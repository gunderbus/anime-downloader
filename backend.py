import random
import time
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp
from bs4 import BeautifulSoup


def normalize_url(url):
    if not url.startswith("http"):
        return "https://" + url
    return url


def is_aniwatch_url(url):
    hostname = urlparse(url).netloc.lower()
    return hostname == "aniwatchtv.to" or hostname.endswith(".aniwatchtv.to")


def download_with_ytdlp(url, extract_audio=False):
    """
    Handles direct downloads with yt-dlp.
    When extract_audio is True, converts the result to MP3.
    """
    timestamp = int(time.time())
    rand_id = random.randint(1000, 9999)
    output_name = f"Anime_Download_{timestamp}_{rand_id}"

    ydl_opts = {
        "format": "bestaudio/best" if extract_audio else "best",
        "outtmpl": f"{output_name}.%(ext)s",
        "quiet": False,  # Set to True if you want less text in the terminal
        "no_warnings": True,
        "noplaylist": True,
    }

    if extract_audio:
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
        ydl_opts["final_ext"] = "mp3"

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
    target_url = normalize_url(target_url)

    print(f"Scanning {target_url}...")

    if is_aniwatch_url(target_url):
        print("Aniwatch URL detected. Downloading and converting to MP3...")
        download_with_ytdlp(target_url, extract_audio=True)
        return

    links = find_all_media(target_url)

    if not links:
        print("No video or m3u8 links detected.")
        return

    print(f"Found {len(links)} potential links. Starting downloads...")
    for link in links:
        download_with_ytdlp(link, extract_audio=True)


# --- Run ---
user_url = input("Enter the URL to scrape: ")
start_scraper(user_url)
