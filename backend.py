import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp
from bs4 import BeautifulSoup


APP_NAME = "Anime Downloader"


def get_app_data_dir():
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
            app_dir = local_app_data / "AnimeDownloader"
        else:
            app_dir = Path.home() / ".anime-downloader"
    else:
        app_dir = Path(__file__).resolve().parent

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


APP_DATA_DIR = get_app_data_dir()
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
DEFAULT_DOWNLOAD_DIR = APP_DATA_DIR / "downloads"
SUPPORTED_STREAM_HOST = "aniwatchtv.to"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
MEGACLOUD_HOST = "megacloud.tv"
MEGACLOUD_REFERER = f"https://{SUPPORTED_STREAM_HOST}/"


def normalize_url(url):
    if not url.startswith("http"):
        return "https://" + url
    return url


def canonicalize_provider_url(url):
    parsed = urlparse(normalize_url(url))
    hostname = parsed.netloc.lower()
    if (
        hostname == SUPPORTED_STREAM_HOST
        or hostname.endswith(f".{SUPPORTED_STREAM_HOST}")
        or "9anime" in hostname
        or "aniwave" in hostname
    ):
        parsed = parsed._replace(netloc=SUPPORTED_STREAM_HOST)
    return parsed.geturl()


def is_aniwatch_url(url):
    hostname = urlparse(normalize_url(url)).netloc.lower()
    return (
        hostname == SUPPORTED_STREAM_HOST
        or hostname.endswith(f".{SUPPORTED_STREAM_HOST}")
        or "9anime" in hostname
        or "aniwave" in hostname
    )


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


def get_show_download_dir(show_name=None):
    output_dir = get_download_dir()
    if show_name:
        output_dir = output_dir / sanitize_filename_part(show_name)
        output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def build_output_path(base_name, extension, show_name=None):
    clean_extension = extension.lstrip(".")
    output_dir = get_show_download_dir(show_name)
    candidate = output_dir / f"{base_name}.{clean_extension}"
    counter = 2

    while candidate.exists():
        candidate = output_dir / f"{base_name} ({counter}).{clean_extension}"
        counter += 1

    return candidate


def build_output_stem(base_name, show_name=None):
    output_dir = get_show_download_dir(show_name)
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
    url = canonicalize_provider_url(url)
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
    output_path = build_output_stem(base_name, show_name=show_name)

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
    canonical_url = canonicalize_provider_url(url)
    parsed = urlparse(canonical_url)
    movie_match = re.search(r"-(\d+)$", parsed.path.rstrip("/"))
    episode_id = dict(
        part.split("=", 1)
        for part in parsed.query.split("&")
        if "=" in part
    ).get("ep")

    movie_id = movie_match.group(1) if movie_match else None
    if movie_id and episode_id:
        return movie_id, episode_id

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(canonical_url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Could not load the anime page to resolve IDs: {exc}") from exc

    page_html = response.text
    if not movie_id:
        movie_id_match = re.search(r'"anime_id"\s*:\s*"(\d+)"', page_html)
        if not movie_id_match:
            movie_id_match = re.search(r'id="wrapper"[^>]*data-id="(\d+)"', page_html)
        if movie_id_match:
            movie_id = movie_id_match.group(1)

    if not episode_id:
        episode_match = re.search(r'["\']episode_id["\']\s*[:=]\s*["\']?(\d+)', page_html)
        if not episode_match:
            episode_match = re.search(r'["\']current_episode["\']\s*[:=]\s*["\']?(\d+)', page_html)
        if episode_match:
            episode_id = episode_match.group(1)

    if not movie_id:
        raise ValueError("Could not determine the anime ID from this link.")

    return movie_id, episode_id


def get_aniwatch_episode_list(target_url):
    target_url = canonicalize_provider_url(target_url)
    movie_id, current_episode_id = extract_movie_and_episode_ids(target_url)
    headers = get_aniwatch_headers(target_url)
    list_response = requests.get(
        f"https://{SUPPORTED_STREAM_HOST}/ajax/v2/episode/list/{movie_id}",
        headers=headers,
        timeout=20,
    )
    list_response.raise_for_status()

    episodes_html = list_response.json().get("html", "")
    if not episodes_html:
        raise ValueError("Aniwatch did not return an episode list.")

    soup = BeautifulSoup(episodes_html, "html.parser")
    episodes = []
    seen_episode_ids = set()

    for episode_link in soup.select("a.ep-item, a.ssl-item.ep-item"):
        episode_id = (episode_link.get("data-id") or "").strip()
        episode_number = (episode_link.get("data-number") or "").strip()
        href = (episode_link.get("href") or "").strip()

        if not episode_id or episode_id in seen_episode_ids:
            continue

        seen_episode_ids.add(episode_id)
        episode_url = urljoin(f"https://{SUPPORTED_STREAM_HOST}", href) if href else target_url
        if href and not episode_url.startswith("http"):
            episode_url = urljoin(target_url, href)

        if not href:
            parsed = urlparse(target_url)
            episode_url = parsed._replace(query=f"ep={episode_id}").geturl()

        episodes.append(
            {
                "url": episode_url,
                "episode_id": episode_id,
                "episode_number": episode_number or None,
                "is_current": bool(current_episode_id) and episode_id == current_episode_id,
            }
        )

    if not episodes:
        raise ValueError("Could not find any episodes in the Aniwatch episode list.")

    def episode_sort_key(item):
        try:
            return (0, float(item["episode_number"]))
        except (TypeError, ValueError):
            return (1, item["episode_id"])

    return sorted(episodes, key=episode_sort_key)


def get_aniwatch_headers(referer):
    return {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": canonicalize_provider_url(referer),
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


def normalize_megacloud_embed_url(embed_url):
    parsed = urlparse(embed_url)
    if parsed.netloc == "megacloud.blog":
        parsed = parsed._replace(netloc=MEGACLOUD_HOST)
    return parsed.geturl()


def extract_megacloud_sources(embed_url, referer=None):
    embed_url = normalize_megacloud_embed_url(embed_url)
    client_key = None
    request_headers = None
    candidate_referers = []
    if referer:
        candidate_referers.append(canonicalize_provider_url(referer))
    candidate_referers.extend([MEGACLOUD_REFERER, f"https://{MEGACLOUD_HOST}/"])

    for candidate_referer in dict.fromkeys(candidate_referers):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Origin": f"https://{MEGACLOUD_HOST}",
            "Referer": candidate_referer,
        }
        for _attempt in range(6):
            embed_response = requests.get(embed_url, headers=headers, timeout=20)
            embed_response.raise_for_status()
            embed_html = embed_response.text

            key_match = re.search(r'_xy_ws\s*=\s*"([A-Za-z0-9]{48})"', embed_html)
            if key_match:
                client_key = key_match.group(1)
                request_headers = headers
                break

            key_match = re.search(r'data-dpi="([A-Za-z0-9]{48})"', embed_html)
            if key_match:
                client_key = key_match.group(1)
                request_headers = headers
                break

            key_match = re.search(
                r'_lk_db\s*=\s*\{x:\s*"([A-Za-z0-9]{16})", y:\s*"([A-Za-z0-9]{16})", z:\s*"([A-Za-z0-9]{16})"\}',
                embed_html,
            )
            if key_match:
                client_key = "".join(key_match.groups())
                request_headers = headers
                break

            key_match = re.search(
                r'<meta name="_gg_fb" content="([A-Za-z0-9]{48})"',
                embed_html,
            )
            if key_match:
                client_key = key_match.group(1)
                request_headers = headers
                break

        if client_key:
            break

    if not client_key or not request_headers:
        raise ValueError("Could not extract MegaCloud client key.")

    source_id_match = re.search(r"/embed-2/v3/e-1/([a-zA-Z0-9]+)\?", embed_url)
    if not source_id_match:
        raise ValueError("Could not extract MegaCloud source ID.")

    sources_response = requests.get(
        f"https://{MEGACLOUD_HOST}/embed-2/v3/e-1/getSources",
        headers=request_headers,
        params={"id": source_id_match.group(1), "_k": client_key},
        timeout=20,
    )
    sources_response.raise_for_status()
    try:
        return sources_response.json()
    except ValueError as exc:
        raise ValueError(
            "MegaCloud returned a non-JSON source response, which usually means the upstream embed domain is no longer serving the player API."
        ) from exc


def resolve_aniwatch_stream_url(target_url, preferred_language="dub"):
    target_url = canonicalize_provider_url(target_url)
    movie_id, episode_id = extract_movie_and_episode_ids(target_url)
    headers = get_aniwatch_headers(target_url)

    servers_response = requests.get(
        f"https://{SUPPORTED_STREAM_HOST}/ajax/v2/episode/servers?episodeId={episode_id}",
        headers=headers,
        timeout=20,
    )
    servers_response.raise_for_status()
    servers_html = servers_response.json().get("html", "")
    preferred_languages = [preferred_language, "sub" if preferred_language == "dub" else "dub"]
    language, server_name, server_id = choose_server_id(servers_html, preferred_languages)

    sources_response = requests.get(
        f"https://{SUPPORTED_STREAM_HOST}/ajax/v2/episode/sources?id={server_id}",
        headers=headers,
        timeout=20,
    )
    sources_response.raise_for_status()
    source_payload = sources_response.json()
    embed_url = source_payload.get("link")
    if not embed_url:
        raise ValueError("Aniwatch did not return an embed URL.")

    source_data = source_payload
    if not source_data.get("sources"):
        source_data = extract_megacloud_sources(embed_url, referer=target_url)
    for source in source_data.get("sources", []):
        file_url = source.get("file", "")
        if file_url.endswith(".m3u8"):
            return (
                movie_id,
                episode_id,
                language,
                server_name,
                file_url,
                source_data.get("tracks", []),
            )

    raise ValueError("No M3U8 stream URL was found for this Aniwatch episode.")


def pick_subtitle_track(tracks):
    subtitle_candidates = []
    for track in tracks or []:
        if not isinstance(track, dict):
            continue
        file_url = track.get("file", "")
        kind = (track.get("kind") or "").lower()
        label = (track.get("label") or "").lower()
        if not file_url:
            continue
        if kind == "captions" or file_url.lower().endswith(tuple(SUBTITLE_EXTENSIONS)) or "caption" in label or "sub" in label:
            subtitle_candidates.append(track)

    if not subtitle_candidates:
        return None

    def subtitle_sort_key(track):
        label = (track.get("label") or "").lower()
        is_default = bool(track.get("default"))
        if "english" in label or label in {"en", "eng"}:
            return (0, 0 if is_default else 1, label)
        return (1, 0 if is_default else 1, label)

    return sorted(subtitle_candidates, key=subtitle_sort_key)[0]


def download_subtitle_track(track, output_file):
    subtitle_url = track.get("file", "")
    if not subtitle_url:
        return

    parsed_path = Path(urlparse(subtitle_url).path)
    extension = parsed_path.suffix.lower() if parsed_path.suffix.lower() in SUBTITLE_EXTENSIONS else ".vtt"
    subtitle_path = output_file.with_suffix(extension)

    print(f"Downloading subtitle track: {subtitle_path.name}")
    response = requests.get(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    subtitle_path.write_bytes(response.content)


def download_m3u8_to_video(
    stream_url,
    show_name=None,
    episode_number=None,
    subtitle_tracks=None,
    download_subtitles=False,
):
    output_file = build_output_path(
        build_episode_name(show_name, episode_number),
        "mp4",
        show_name=show_name,
    )
    ffmpeg_headers = (
        "User-Agent: Mozilla/5.0\r\n"
        f"Referer: https://{MEGACLOUD_HOST}/\r\n"
        f"Origin: https://{MEGACLOUD_HOST}\r\n"
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
        if download_subtitles:
            subtitle_track = pick_subtitle_track(subtitle_tracks)
            if subtitle_track:
                try:
                    download_subtitle_track(subtitle_track, output_file)
                except Exception as exc:
                    print(f"Could not download subtitle track: {exc}")
            else:
                print("No subtitle track was available for this episode.")
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


def start_scraper(target_url, selected_episode_ids=None, preferred_language="dub"):
    target_url = canonicalize_provider_url(target_url)
    output_dir = get_download_dir()
    selected_episode_ids = set(selected_episode_ids or [])

    print(f"Scanning {target_url}...")
    print(f"Download folder: {output_dir}")

    if is_aniwatch_url(target_url):
        print("Aniwatch URL detected. Resolving season episode list...")
        try:
            show_name, _ = extract_media_details(target_url)
            episodes = get_aniwatch_episode_list(target_url)
            if selected_episode_ids:
                episodes = [
                    episode
                    for episode in episodes
                    if episode["episode_id"] in selected_episode_ids
                ]
                if not episodes:
                    print("No selected episodes matched this season.")
                    return

            print(f"Found {len(episodes)} episodes. Starting season download...")

            for index, episode in enumerate(episodes, start=1):
                episode_url = episode["url"]
                episode_number = episode["episode_number"]
                marker = " (from pasted link)" if episode["is_current"] else ""
                print(
                    f"[{index}/{len(episodes)}] Resolving Episode {episode_number or '?'}{marker}: {episode_url}"
                )
                try:
                    _, _, language, server_name, stream_url, subtitle_tracks = resolve_aniwatch_stream_url(
                        episode_url,
                        preferred_language=preferred_language,
                    )
                    print(
                        f"Using {language.upper()} server: {server_name}. Starting video download..."
                    )
                    download_m3u8_to_video(
                        stream_url,
                        show_name,
                        episode_number,
                        subtitle_tracks=subtitle_tracks,
                        download_subtitles=language == "sub",
                    )
                except Exception as e:
                    print(
                        f"Could not resolve Aniwatch stream for Episode {episode_number or '?'}: {e}"
                    )
        except Exception as e:
            print(f"Could not resolve Aniwatch season: {e}")
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


def scan_download_catalog():
    download_dir = get_download_dir()
    catalog = {}

    for file_path in sorted(download_dir.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        relative_parts = file_path.relative_to(download_dir).parts
        if len(relative_parts) > 1:
            show_name = relative_parts[0]
        else:
            show_name = sanitize_filename_part(file_path.stem.split(" - Episode ")[0])

        match = re.search(r"Episode\s+(\d+(?:\.\d+)?)", file_path.stem, re.IGNORECASE)
        episode_label = match.group(1) if match else file_path.stem
        subtitle_files = [
            str(candidate)
            for candidate in file_path.parent.glob(f"{file_path.stem}.*")
            if candidate.suffix.lower() in SUBTITLE_EXTENSIONS
        ]

        catalog.setdefault(show_name, []).append(
            {
                "episode_label": episode_label,
                "title": file_path.stem,
                "path": str(file_path),
                "subtitles": subtitle_files,
            }
        )

    def episode_sort_key(item):
        try:
            return (0, float(item["episode_label"]))
        except (TypeError, ValueError):
            return (1, item["title"].lower())

    return {
        show_name: sorted(episodes, key=episode_sort_key)
        for show_name, episodes in sorted(catalog.items(), key=lambda item: item[0].lower())
    }


def open_in_system_player(path):
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {target}")

    if os.name == "nt":
        os.startfile(str(target))
        return

    command = ["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)]
    subprocess.Popen(command)


def main():
    user_url = input("Enter the URL to scrape: ")
    start_scraper(user_url)


if __name__ == "__main__":
    main()
