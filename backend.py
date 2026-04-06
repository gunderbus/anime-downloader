import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp
from bs4 import BeautifulSoup


SETTINGS_FILE = Path(__file__).with_name("settings.json")
DEFAULT_DOWNLOAD_DIR = Path(__file__).with_name("downloads")


def normalize_url(url):
    if not url.startswith("http"):
        return "https://" + url
    return url


def is_aniwatch_url(url):
    hostname = urlparse(url).netloc.lower()
    return hostname == "aniwatchtv.to" or hostname.endswith(".aniwatchtv.to")


def load_settings():
    if not SETTINGS_FILE.exists():
        return {"download_dir": str(DEFAULT_DOWNLOAD_DIR)}

    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except (json.JSONDecodeError, OSError):
        return {"download_dir": str(DEFAULT_DOWNLOAD_DIR)}

    settings.setdefault("download_dir", str(DEFAULT_DOWNLOAD_DIR))
    return settings


def save_settings(settings):
    merged_settings = load_settings()
    merged_settings.update(settings)

    with SETTINGS_FILE.open("w", encoding="utf-8") as settings_file:
        json.dump(merged_settings, settings_file, indent=2)


def get_download_dir():
    settings = load_settings()
    output_dir = Path(settings.get("download_dir") or DEFAULT_DOWNLOAD_DIR).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def set_download_dir(path):
    resolved_path = Path(path).expanduser()
    resolved_path.mkdir(parents=True, exist_ok=True)
    save_settings({"download_dir": str(resolved_path)})
    return resolved_path


def sanitize_filename_part(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned or "Anime"


def build_episode_name(show_name=None, episode_number=None):
    clean_show_name = sanitize_filename_part(show_name or "Anime")
    if episode_number:
        return sanitize_filename_part(f"{clean_show_name} - Episode {episode_number}")
    return clean_show_name


def build_output_path(base_name, extension):
    clean_extension = extension.lstrip(".")
    output_dir = get_download_dir()
    candidate = output_dir / f"{base_name}.{clean_extension}"
    counter = 2

    while candidate.exists():
        candidate = output_dir / f"{base_name} ({counter}).{clean_extension}"
        counter += 1

    return candidate


def build_output_stem(base_name):
    output_dir = get_download_dir()
    candidate = output_dir / base_name
    counter = 2

    while any(output_dir.glob(f"{candidate.name}.*")):
        candidate = output_dir / f"{base_name} ({counter})"
        counter += 1

    return candidate


def extract_episode_number(text):
    if not text:
        return None

    patterns = [
        r"\bEpisode\s+(\d+(?:\.\d+)?)\b",
        r"\bEP\s+(\d+(?:\.\d+)?)\b",
        r"\bE(\d+(?:\.\d+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_media_details(url):
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1]
    show_name = None
    episode_number = None

    if slug:
        slug_match = re.match(r"(?P<name>.+)-(\d+)$", slug)
        if slug_match:
            show_name = slug_match.group("name").replace("-", " ").strip()

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except requests.RequestException:
        return show_name, episode_number

    title_sources = [
        soup.title.string if soup.title and soup.title.string else "",
        (soup.find("meta", property="og:title") or {}).get("content", ""),
        (soup.find("meta", attrs={"name": "title"}) or {}).get("content", ""),
        soup.get_text(" ", strip=True)[:5000],
    ]

    for title_text in title_sources:
        if not title_text:
            continue

        if not episode_number:
            episode_number = extract_episode_number(title_text)

        if not show_name:
            show_match = re.search(
                r"Watch\s+(.+?)\s+Episode\s+\d+(?:\.\d+)?",
                title_text,
                re.IGNORECASE,
            )
            if show_match:
                show_name = show_match.group(1).strip(" -|:")
                break

    return show_name, episode_number


def download_with_ytdlp(url, extract_audio=False, show_name=None, episode_number=None):
    """
    Handles direct downloads with yt-dlp.
    When extract_audio is True, converts the result to MP3.
    """
    if not show_name or not episode_number:
        guessed_show_name, guessed_episode_number = extract_media_details(url)
        show_name = show_name or guessed_show_name
        episode_number = episode_number or guessed_episode_number

    base_name = build_episode_name(show_name, episode_number)
    output_path = build_output_stem(base_name)

    ydl_opts = {
        "format": "bestaudio/best" if extract_audio else "best",
        "outtmpl": str(output_path) + ".%(ext)s",
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
    print(f"Saving to: {output_path.parent}")
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


def choose_server_id(servers_html, preferred_languages=None):
    preferred_languages = preferred_languages or ["dub", "sub"]
    preferred_servers = ["MegaCloud", "VidSrc", "T-Cloud"]

    for language in preferred_languages:
        for server_name in preferred_servers:
            pattern = (
                r'<div class="item server-item"[^>]*data-type="'
                + re.escape(language)
                + r'"[^>]*data-id="([^"]+)"[^>]*>'
                r'\s*<a [^>]*class="btn">\s*'
                + re.escape(server_name)
                + r"\s*</a>"
            )
            match = re.search(pattern, servers_html, re.IGNORECASE)
            if match:
                return language, server_name, match.group(1)

    fallback = re.search(
        r'<div class="item server-item"[^>]*data-type="([^"]+)"[^>]*data-id="([^"]+)"',
        servers_html,
        re.IGNORECASE,
    )
    if fallback:
        return fallback.group(1), "unknown", fallback.group(2)

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
    language, server_name, server_id = choose_server_id(servers_html)

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
            return movie_id, episode_id, language, server_name, file_url

    raise ValueError("No M3U8 stream URL was found for this Aniwatch episode.")


def download_m3u8_to_video(stream_url, show_name=None, episode_number=None):
    output_file = build_output_path(
        build_episode_name(show_name, episode_number),
        "mp4",
    )
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
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    print(f"--- Downloading video file: {output_file} ---")
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print("ffmpeg is not installed or not available in PATH.")
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed while downloading the video stream: {e}")


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
    output_dir = get_download_dir()

    print(f"Scanning {target_url}...")
    print(f"Download folder: {output_dir}")

    if is_aniwatch_url(target_url):
        print("Aniwatch URL detected. Resolving dub stream and downloading video...")
        try:
            show_name, episode_number = extract_media_details(target_url)
            _, _, language, server_name, stream_url = resolve_aniwatch_stream_url(
                target_url
            )
            print(
                f"Using {language.upper()} server: {server_name}. Starting video download..."
            )
            download_m3u8_to_video(stream_url, show_name, episode_number)
        except Exception as e:
            print(f"Could not resolve Aniwatch stream: {e}")
        return

    links = find_all_media(target_url)

    if not links:
        print("No video or m3u8 links detected.")
        return

    print(f"Found {len(links)} potential links. Starting downloads...")
    show_name, episode_number = extract_media_details(target_url)
    for link in links:
        download_with_ytdlp(
            link,
            extract_audio=False,
            show_name=show_name,
            episode_number=episode_number,
        )


def main():
    user_url = input("Enter the URL to scrape: ")
    start_scraper(user_url)


if __name__ == "__main__":
    main()
