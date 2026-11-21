#!/usr/bin/env python3
"""Copies NASA FIRMS' fires of the last day into a file of the site, with only the columns Skyline's app reads.

FIRMS' files don't allow requests from other sites, so a page can't read them itself. NASA's data is open, with
FIRMS credited, which the app does.

    python3 tools/mirror_firms.py fires/detections.json

The file is {"mirrored", "source", "csv"}: when it was copied, FIRMS' Last-Modified, and FIRMS' own CSV cut to the
columns in COLUMNS, which the app's parseFirms and mergedFires read as they read the whole file, so how detections
become fires is written once, in Kotlin.
FIRMS' file is downloaded only when its Last-Modified differs from the site's copy's, as it ignores If-Modified-Since;
the copy stays when it doesn't or FIRMS can't be read. Its last line is "changed" when FIRMS has a newer file or the
site's copy is over 2 hours old, else "unchanged", so the site is published again only then.
"""

import csv
import datetime
import io
import json
import pathlib
import sys
import urllib.request

FILE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv"
PUBLISHED = "https://skyline.arrufat.io/fires/detections.json"
AGENT = "skyline-site-mirror (+https://skyline.arrufat.io)"
COLUMNS = ["latitude", "longitude", "acq_date", "acq_time", "confidence", "frp"]
# The app refuses a copy over 6 hours old.
RENEW = datetime.timedelta(hours=2)


def fetch(url, method="GET"):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT}, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), response.headers.get("Last-Modified")


def trimmed(text):
    rows = csv.DictReader(io.StringIO(text))
    missing = set(COLUMNS) - set(rows.fieldnames or [])
    if missing:
        raise ValueError(f"no {', '.join(sorted(missing))}")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    count = 0
    for row in rows:
        writer.writerow(row[column] for column in COLUMNS)
        count += 1
    return out.getvalue(), count


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
        if published is not None and "csv" in published and latest and published.get("source") == latest:
            # The same fires, copied again only to renew their time before the app takes them for stopped.
            renew = is_old(published, now)
            if renew:
                published["mirrored"] = stamp
            path.write_text(json.dumps(published, separators=(",", ":")), encoding="utf-8")
            print(f"FIRMS has nothing newer than {latest}")
            print("changed" if renew else "unchanged")
            return
        body, modified = fetch(FILE)
        text, count = trimmed(body.decode("utf-8"))
        if count < 100:
            raise ValueError(f"only {count} detections")
    except Exception as error:
        print(f"FIRMS: {error}", file=sys.stderr)
        if published is not None:
            path.write_text(json.dumps(published, separators=(",", ":")), encoding="utf-8")
        print("unchanged")
        return
    copy = {"mirrored": stamp, "source": modified, "csv": text}
    path.write_text(json.dumps(copy, separators=(",", ":")), encoding="utf-8")
    print(f"{count} detections, {path.stat().st_size / 1e6:.1f} MB, from {modified}")
    print("changed")


if __name__ == "__main__":
    main()
