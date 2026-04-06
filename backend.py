import random
import re
import subprocess
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


def build_output_name(extension):
    timestamp = int(time.time())
    rand_id = random.randint(1000, 9999)
    return f"Anime_Download_{timestamp}_{rand_id}.{extension}"


def download_with_ytdlp(url, extract_audio=False):
    """
    Handles direct downloads with yt-dlp.
    When extract_audio is True, converts the result to MP3.
    """
    output_name = build_output_name("%(ext)s").replace(".%(ext)s", "")

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


def extract_movie_and_episode_ids(url):
    parsed = urlparse(url)
    movie_match = re.search(r"-(\d+)$", parsed.path.rstrip("/"))
    episode_id = dict(
        part.split("=", 1)
        for part in parsed.query.split("&")
        if "=" in part
    ).get("ep")

    if not movie_match or not episode_id:
        raise ValueError("Could not determine Aniwatch movie or episode ID from URL.")

    return movie_match.group(1), episode_id


def get_aniwatch_headers(referer):
    return {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }


def choose_server_id(servers_html):
    preferred_servers = ["MegaCloud", "VidSrc", "T-Cloud"]

    for server_name in preferred_servers:
        pattern = (
            r'<div class="item server-item"[^>]*data-id="([^"]+)"[^>]*>'
            r'\s*<a [^>]*class="btn">\s*'
            + re.escape(server_name)
            + r"\s*</a>"
        )
        match = re.search(pattern, servers_html, re.IGNORECASE)
        if match:
            return match.group(1)

    fallback = re.search(r'data-id="([^"]+)"', servers_html)
    if fallback:
        return fallback.group(1)

    raise ValueError("No supported Aniwatch server IDs were found.")


def extract_megacloud_sources(embed_url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://megacloud.blog",
        "Referer": "https://megacloud.blog/",
    }
    embed_response = requests.get(embed_url, headers=headers, timeout=20)
    embed_response.raise_for_status()

    key_match = re.search(
        r'([a-zA-Z0-9]{48})|x: "([a-zA-Z0-9]{16})", y: "([a-zA-Z0-9]{16})", z: "([a-zA-Z0-9]{16})"};',
        embed_response.text,
    )
    if not key_match:
        raise ValueError("Could not extract MegaCloud client key.")

    client_key = "".join(part for part in key_match.groups() if part)
    source_id_match = re.search(r"/embed-2/v3/e-1/([a-zA-Z0-9]+)\?", embed_url)
    if not source_id_match:
        raise ValueError("Could not extract MegaCloud source ID.")

    sources_response = requests.get(
        "https://megacloud.blog/embed-2/v3/e-1/getSources",
        headers=headers,
        params={"id": source_id_match.group(1), "_k": client_key},
        timeout=20,
    )
    sources_response.raise_for_status()
    return sources_response.json()


def resolve_aniwatch_stream_url(target_url):
    movie_id, episode_id = extract_movie_and_episode_ids(target_url)
    headers = get_aniwatch_headers(target_url)

    servers_response = requests.get(
        f"https://aniwatchtv.to/ajax/v2/episode/servers?episodeId={episode_id}",
        headers=headers,
        timeout=20,
    )
    servers_response.raise_for_status()
    servers_html = servers_response.json().get("html", "")
    server_id = choose_server_id(servers_html)

    sources_response = requests.get(
        f"https://aniwatchtv.to/ajax/v2/episode/sources?id={server_id}",
        headers=headers,
        timeout=20,
    )
    sources_response.raise_for_status()
    embed_url = sources_response.json().get("link")
    if not embed_url:
        raise ValueError("Aniwatch did not return an embed URL.")

    source_data = extract_megacloud_sources(embed_url)
    for source in source_data.get("sources", []):
        file_url = source.get("file", "")
        if file_url.endswith(".m3u8"):
            return movie_id, episode_id, file_url

    raise ValueError("No M3U8 stream URL was found for this Aniwatch episode.")


def download_m3u8_to_mp3(stream_url):
    output_file = build_output_name("mp3")
    ffmpeg_headers = (
        "User-Agent: Mozilla/5.0\r\n"
        "Referer: https://megacloud.blog/\r\n"
        "Origin: https://megacloud.blog\r\n"
    )

    command = [
        "ffmpeg",
        "-y",
        "-headers",
        ffmpeg_headers,
        "-i",
        stream_url,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        output_file,
    ]

    print(f"--- Converting stream to MP3: {output_file} ---")
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print("ffmpeg is not installed or not available in PATH.")
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed while converting stream to MP3: {e}")


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
        print("Aniwatch URL detected. Resolving stream and converting to MP3...")
        try:
            _, _, stream_url = resolve_aniwatch_stream_url(target_url)
            download_m3u8_to_mp3(stream_url)
        except Exception as e:
            print(f"Could not resolve Aniwatch stream: {e}")
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
