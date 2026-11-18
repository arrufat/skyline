#!/usr/bin/env python3
"""Copies MeteoAlarm's feeds, trimmed to what Skyline's browser app reads, into a folder of the site.

MeteoAlarm's feeds don't allow requests from other sites, so a page can't read them itself. Its terms allow
passing them on with the source shown as "EUMETNET – MeteoAlarm" and each warning's time of issue, which the app does.

    python3 tools/mirror_meteoalarm.py warnings/meteoalarm

Each file keeps the feed's own JSON shape, plus "mirrored", when it was copied. A feed that can't be read keeps the
copy the site has now. Its last line is "changed" when any warning differs from the site's copy or that copy is
over 45 minutes old, else "unchanged", so the site is published again only then.
"""

import datetime
import hashlib
import json
import pathlib
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

FEED = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-"
PUBLISHED = "https://skyline.arrufat.io/warnings/meteoalarm/"
AGENT = "skyline-site-mirror (+https://skyline.arrufat.io)"

# The members, as the app's MeteoAlarm.kt lists them.
MEMBERS = [
    "andorra", "austria", "belgium", "bosnia-herzegovina", "bulgaria", "croatia", "cyprus", "czechia", "denmark",
    "estonia", "finland", "france", "germany", "greece", "hungary", "iceland", "ireland", "israel", "italy", "latvia",
    "lithuania", "luxembourg", "malta", "moldova", "montenegro", "netherlands", "norway", "poland", "portugal",
    "republic-of-north-macedonia", "romania", "serbia", "slovakia", "slovenia", "spain", "sweden", "switzerland",
    "ukraine", "united-kingdom",
]

# What the app reads of each language's text.
INFO_FIELDS = ("language", "event", "headline", "description", "instruction", "onset", "effective", "expires", "senderName", "web")
PARAMETERS = ("awareness_level", "awareness_type")
# Yellow, orange, and red; 1 is green, no warning.
LEVELS = ("2", "3", "4")
RENEW = datetime.timedelta(minutes=45)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def is_over(info, now):
    try:
        return datetime.datetime.fromisoformat(info["expires"]) < now
    except (KeyError, TypeError, ValueError):
        return False


def is_old(published, now):
    """Whether the site's copy needs its time renewed, as the app refuses one over 3 hours old."""
    try:
        return now - datetime.datetime.fromisoformat(published["mirrored"]) > RENEW
    except (KeyError, TypeError, ValueError):
        return True


def level(parameters):
    for parameter in parameters:
        if parameter["valueName"] == "awareness_level":
            return str(parameter.get("value", "")).split(";")[0].strip()
    return None


def trimmed(feed, now):
    """The warnings in force or still to start, with only what the app reads; each area and outline once per alert."""
    warnings = []
    for entry in feed.get("warnings", []):
        alert = entry.get("alert") or {}
        if alert.get("status") != "Actual" or alert.get("msgType") == "Cancel":
            continue
        infos, codes, outlines = [], set(), set()
        for info in alert.get("info", []):
            parameters = [
                {"valueName": p["valueName"], "value": p.get("value", "")}
                for p in info.get("parameter", [])
                if p.get("valueName") in PARAMETERS
            ]
            if is_over(info, now) or level(parameters) not in LEVELS:
                continue
            areas = []
            for area in info.get("area", []):
                geocode = [g for g in area.get("geocode", []) if "value" in g and g["value"] not in codes]
                polygon = [p for p in area.get("polygon", []) if p not in outlines]
                codes.update(g["value"] for g in geocode)
                outlines.update(polygon)
                if geocode or polygon:
                    areas.append({
                        "geocode": [{"valueName": g.get("valueName", ""), "value": g["value"]} for g in geocode],
                        "polygon": polygon,
                    })
            kept = {field: info[field] for field in INFO_FIELDS if info.get(field) is not None}
            kept["parameter"] = parameters
            kept["area"] = areas
            infos.append(kept)
        if infos:
            warnings.append({"alert": {"status": "Actual", "msgType": alert.get("msgType"), "sent": alert.get("sent"), "info": infos}})
    return warnings


def text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def mirrored(member, now):
    """The member's file and whether its warnings differ from the site's copy; the site's copy when its feed fails."""
    try:
        published = json.loads(fetch(f"{PUBLISHED}{member}.json"))
    except Exception:
        published = None
    try:
        warnings = trimmed(json.loads(fetch(FEED + member)), now)
    except Exception as error:
        print(f"{member}: {error}", file=sys.stderr)
        return published, False
    changed = published is None or text(published.get("warnings")) != text(warnings) or is_old(published, now)
    return {"mirrored": now.isoformat(timespec="seconds"), "warnings": warnings}, changed


def main():
    folder = pathlib.Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda member: mirrored(member, now), MEMBERS))
    written = 0
    for member, (feed, _) in zip(MEMBERS, results):
        if feed is not None:
            (folder / f"{member}.json").write_text(text(feed), encoding="utf-8")
            written += 1
    if written < len(MEMBERS) // 2:
        sys.exit(f"only {written} of {len(MEMBERS)} feeds could be written")
    digest = hashlib.sha256("".join(text(feed) for feed, _ in results if feed).encode()).hexdigest()[:12]
    print(f"{written} feeds, {sum(f.stat().st_size for f in folder.glob('*.json')) / 1e6:.1f} MB, {digest}")
    print("changed" if any(changed for _, changed in results) else "unchanged")


if __name__ == "__main__":
    main()
