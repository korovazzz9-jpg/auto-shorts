"""Скачивает фоновую инструментальную музыку с Internet Archive (archive.org) — бесплатно,
без ключа, только треки с коммерчески безопасной лицензией (CC0/CC-BY/CC-BY-SA/public domain)."""
from __future__ import annotations

import random

import requests

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

SAFE_LICENSE_MARKERS = ["publicdomain", "/zero/", "cc0", "/by/", "/by-sa/"]
UNSAFE_LICENSE_MARKERS = ["-nc", "-nd", "noncommercial", "noderivs"]

SEARCH_QUERIES = [
    "ambient instrumental background",
    "cinematic ambient instrumental",
    "calm piano instrumental",
    "uplifting ambient electronic instrumental",
    "curious mysterious ambient instrumental",
]


def _is_safe_license(license_url: str | None) -> bool:
    if not license_url:
        return False
    url = license_url.lower()
    if any(marker in url for marker in UNSAFE_LICENSE_MARKERS):
        return False
    return any(marker in url for marker in SAFE_LICENSE_MARKERS)


def _search_candidates(query: str) -> list[str]:
    params = {
        "q": f'collection:opensource_audio AND mediatype:audio AND ({query})',
        "fl[]": ["identifier"],
        "rows": 20,
        "output": "json",
    }
    response = requests.get(SEARCH_URL, params=params, timeout=30)
    response.raise_for_status()
    docs = response.json().get("response", {}).get("docs", [])
    return [d["identifier"] for d in docs]


def _find_mp3_file(identifier: str) -> dict | None:
    response = requests.get(METADATA_URL.format(identifier=identifier), timeout=30)
    response.raise_for_status()
    data = response.json()

    license_url = data.get("metadata", {}).get("licenseurl")
    if not _is_safe_license(license_url):
        return None

    mp3_files = [f for f in data.get("files", []) if f["name"].lower().endswith(".mp3")]
    if not mp3_files:
        return None
    mp3_files.sort(key=lambda f: int(f.get("size", 0) or 0), reverse=True)
    return {"identifier": identifier, "filename": mp3_files[0]["name"]}


def fetch_random_track(out_path: str) -> bool:
    """Returns True if a track was found and saved to out_path."""
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)

    for query in queries:
        try:
            candidates = _search_candidates(query)
        except Exception:
            continue
        random.shuffle(candidates)

        for identifier in candidates[:8]:
            try:
                found = _find_mp3_file(identifier)
            except Exception:
                continue
            if not found:
                continue
            url = DOWNLOAD_URL.format(identifier=found["identifier"], filename=found["filename"])
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
            except Exception:
                continue
            with open(out_path, "wb") as f:
                f.write(response.content)
            return True

    return False


if __name__ == "__main__":
    ok = fetch_random_track("test_music_track.mp3")
    print("Найден трек:" if ok else "Ничего не найдено.")
