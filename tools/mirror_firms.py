#!/usr/bin/env python3
"""Copies NASA FIRMS' fires of the last day, merged as Skyline's app merges them, into a file of the site.

FIRMS' files don't allow requests from other sites, so a page can't read them itself. NASA's data is open, with
FIRMS credited, which the app does.

    python3 tools/mirror_firms.py fires/firms.json

The file is {"mirrored", "source", "fires"}: when it was copied, FIRMS' Last-Modified, and each fire as [latitude,
longitude, the second it was last seen, its heat in MW], the least heat first. A fire is every detection in a square
of 0.05°, as the app's mergedFires has it: their heat added up, placed where most of it is, seen when the latest was.
FIRMS' file is downloaded only when its Last-Modified differs from the site's copy's, as it ignores If-Modified-Since;
the copy stays when it doesn't or FIRMS can't be read. Its last line is "changed" when FIRMS has a newer file or the
site's copy is over 2 hours old, else "unchanged", so the site is published again only then.
"""

import collections
import csv
import datetime
import io
import json
import math
import pathlib
import sys
import urllib.request

FILE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv"
PUBLISHED = "https://skyline.arrufat.io/fires/firms.json"
AGENT = "skyline-site-mirror (+https://skyline.arrufat.io)"
CELL = 0.05
# The app refuses a copy over 6 hours old.
RENEW = datetime.timedelta(hours=2)
# MODIS's own line between low and nominal; VIIRS says low, nominal, or high.
LOW_CONFIDENCE = 30


def fetch(url, method="GET"):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT}, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), response.headers.get("Last-Modified")


def is_sure(confidence):
    confidence = confidence.strip()
    if confidence in ("low", "l"):
        return False
    try:
        return int(confidence) >= LOW_CONFIDENCE
    except ValueError:
        return True


def detections(text):
    for row in csv.DictReader(io.StringIO(text)):
        try:
            if not is_sure(row["confidence"]):
                continue
            hhmm = int(row["acq_time"])
            seen = datetime.datetime.fromisoformat(row["acq_date"]).replace(
                hour=hhmm // 100, minute=hhmm % 100, tzinfo=datetime.timezone.utc
            )
            yield float(row["latitude"]), float(row["longitude"]), int(seen.timestamp()), float(row["frp"] or 0)
        except (KeyError, ValueError):
            continue


def merged(found):
    cells = collections.defaultdict(list)
    for fire in found:
        cells[(math.floor(fire[0] / CELL), math.floor(fire[1] / CELL))].append(fire)
    fires = []
    for cell in cells.values():
        heat = sum(fire[3] for fire in cell)

        def mean(index):
            if heat > 0:
                return sum(fire[index] * fire[3] for fire in cell) / heat
            return sum(fire[index] for fire in cell) / len(cell)

        fires.append([round(mean(0), 3), round(mean(1), 3), max(fire[2] for fire in cell), round(heat, 1)])
    return sorted(fires, key=lambda fire: fire[3])


def is_old(published, now):
    try:
        return now - datetime.datetime.fromisoformat(published["mirrored"].replace("Z", "+00:00")) > RENEW
    except (KeyError, TypeError, ValueError, AttributeError):
        return True


def main():
    path = pathlib.Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        published = json.loads(fetch(PUBLISHED)[0])
    except Exception:
        published = None
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        latest = fetch(FILE, method="HEAD")[1]
        if published is not None and latest and published.get("source") == latest:
            # The same fires, copied again only to renew their time before the app takes them for stopped.
            renew = is_old(published, now)
            if renew:
                published["mirrored"] = stamp
            path.write_text(json.dumps(published, separators=(",", ":")), encoding="utf-8")
            print(f"FIRMS has nothing newer than {latest}")
            print("changed" if renew else "unchanged")
            return
        body, modified = fetch(FILE)
        fires = merged(detections(body.decode("utf-8")))
        if len(fires) < 100:
            raise ValueError(f"only {len(fires)} fires")
    except Exception as error:
        print(f"FIRMS: {error}", file=sys.stderr)
        if published is not None:
            path.write_text(json.dumps(published, separators=(",", ":")), encoding="utf-8")
        print("unchanged")
        return
    copy = {"mirrored": stamp, "source": modified, "fires": fires}
    path.write_text(json.dumps(copy, separators=(",", ":")), encoding="utf-8")
    print(f"{len(fires)} fires, {path.stat().st_size / 1e6:.1f} MB, from {modified}")
    print("changed")


if __name__ == "__main__":
    main()
