#!/usr/bin/env python3
"""Create the cron-job.org jobs that start this repo's workflows on time.

GitHub's own `schedule:` runs late or not at all (Nov 2026: 3 of ~74 runs of a 15-min
cron). cron-job.org calls GitHub's workflow_dispatch API on a precise schedule instead;
the checks themselves still run on GitHub, unchanged.

  python3 scripts/setup_triggers.py            create/update the jobs (asks for 2 keys, hidden)
  python3 scripts/setup_triggers.py --status   show the jobs: last result, next run
  python3 scripts/setup_triggers.py --remove   delete the jobs

Keys (never printed):
  - cron-job.org API key (Console > Settings > API). Stored in ~/.config/hutwatch with
    owner-only permissions, so --status works later. Or set CRONJOB_ORG_API_KEY.
  - GitHub fine-grained token: repository frhl/dolomites-hut-watch only, permission
    "Actions: Read and write". Not stored here; it lives in the cron-job.org jobs.
    Or set HUTWATCH_DISPATCH_TOKEN.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "frhl/dolomites-hut-watch"
REF = "main"
PREFIX = "hut-watch: "
CRONJOB_API = "https://api.cron-job.org"
GITHUB_API = "https://api.github.com"
UA = "hut-booking-watch-setup/1.0 (github.com/frhl/dolomites-hut-watch)"
KEY_FILE = Path.home() / ".config" / "hutwatch" / "cronjob_org_api_key"

ALL = [-1]
FULL_MIN = [3, 18, 33, 48]                      # every 15 min (off the busy :00)
NUV_MIN = [8, 13, 23, 28, 38, 43, 53, 58]       # the other 5-min slots

# title, workflow file, dispatch inputs, schedule (UTC). expiresAt = YYYYMMDDhhmmss.
JOBS = [
    (PREFIX + "cancellation-watch every 15 min", "beds.yml", {"scope": "all"},
     dict(minutes=FULL_MIN, hours=ALL, mdays=ALL, months=ALL, wdays=ALL, expiresAt=20270629000000)),
    (PREFIX + "Nuvolau every 5 min, 15-31 Dec", "beds.yml", {"scope": "nuvolau"},
     dict(minutes=NUV_MIN, hours=ALL, mdays=list(range(15, 32)), months=[12], wdays=ALL,
          expiresAt=20270216000000)),
    (PREFIX + "Nuvolau every 5 min, January", "beds.yml", {"scope": "nuvolau"},
     dict(minutes=NUV_MIN, hours=ALL, mdays=ALL, months=[1], wdays=ALL, expiresAt=20270216000000)),
    (PREFIX + "Nuvolau every 5 min, 1-15 Feb", "beds.yml", {"scope": "nuvolau"},
     dict(minutes=NUV_MIN, hours=ALL, mdays=list(range(1, 16)), months=[2], wdays=ALL,
          expiresAt=20270216000000)),
    (PREFIX + "page-watch every 4 h", "pages.yml", {},
     dict(minutes=[23], hours=[0, 4, 8, 12, 16, 20], mdays=ALL, months=ALL, wdays=ALL,
          expiresAt=20270629120000)),
    (PREFIX + "Nuvolau 1-min probe, start 31 Jan 21:00 UTC", "nuvolau-dense.yml", {},
     dict(minutes=[0], hours=[21], mdays=[31], months=[1], wdays=ALL, expiresAt=20270201000000)),
    (PREFIX + "Nuvolau 1-min probe, 1-2 Feb every 3 h", "nuvolau-dense.yml", {},
     dict(minutes=[0], hours=list(range(0, 24, 3)), mdays=[1, 2], months=[2], wdays=ALL,
          expiresAt=20270203000000)),
]


class ApiError(Exception):
    pass


def call(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "User-Agent": UA,
        "Accept": "application/vnd.github+json" if url.startswith(GITHUB_API) else "application/json",
        **({"Content-Type": "application/json"} if data is not None else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        # Status only: error bodies are not printed (they could quote request details).
        raise ApiError(f"{method} {url.split('?')[0]} -> HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"{method} {url} -> network error ({type(e.reason).__name__})") from None


def job_body(title: str, workflow: str, inputs: dict, schedule: dict, gh_token: str) -> dict:
    payload = {"ref": REF, **({"inputs": inputs} if inputs else {})}
    return {
        "enabled": True,
        "title": title,
        "url": f"{GITHUB_API}/repos/{REPO}/actions/workflows/{workflow}/dispatches",
        "requestMethod": 1,  # POST
        "requestTimeout": 30,
        "saveResponses": False,
        "redirectSuccess": False,
        "schedule": {"timezone": "UTC", **schedule},
        "notification": {"onFailure": True, "onFailureCount": 3, "onSuccess": True, "onDisable": True},
        "extendedData": {
            "headers": {
                "Authorization": f"Bearer {gh_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "hut-booking-watch-trigger/1.0 (cron-job.org; github.com/frhl/dolomites-hut-watch)",
            },
            "body": json.dumps(payload),
        },
    }


def api_key(ask: bool) -> str:
    k = os.environ.get("CRONJOB_ORG_API_KEY", "").strip()
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text().strip()
    if not k and ask:
        k = getpass.getpass("cron-job.org API key (hidden): ").strip()
    if not k:
        sys.exit("No cron-job.org API key (set CRONJOB_ORG_API_KEY or run without --status first).")
    return k


def save_key(k: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(KEY_FILE.parent, 0o700)
    old = os.umask(0o077)
    try:
        KEY_FILE.write_text(k)
    finally:
        os.umask(old)
    os.chmod(KEY_FILE, 0o600)


def our_jobs(key: str) -> list[dict]:
    _, d = call("GET", f"{CRONJOB_API}/jobs", key)
    return [j for j in d.get("jobs", []) if str(j.get("title", "")).startswith(PREFIX)]


def check_token(gh_token: str) -> None:
    _, d = call("GET", f"{GITHUB_API}/repos/{REPO}/actions/workflows", gh_token)
    files = {Path(w["path"]).name for w in d.get("workflows", [])}
    missing = {wf for _, wf, _, _ in JOBS} - files
    if missing:
        sys.exit(f"Token can read the repo, but these workflows are missing: {sorted(missing)}")
    # One real dispatch proves the token can start runs (it also starts a normal check now).
    status, _ = call("POST", f"{GITHUB_API}/repos/{REPO}/actions/workflows/beds.yml/dispatches",
                     gh_token, {"ref": REF, "inputs": {"scope": "all"}})
    print(f"GitHub token OK: started one cancellation-watch run (HTTP {status}).")


def ts(x) -> str:
    return dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if x else "-"


STATUS = {0: "not run yet", 1: "OK", 2: "DNS error", 3: "could not connect", 4: "HTTP error",
          5: "timeout", 6: "too much response data", 7: "invalid URL", 8: "internal error",
          9: "unknown failure", 10: "challenge page"}


def show(key: str) -> None:
    jobs = sorted(our_jobs(key), key=lambda j: j["title"])
    if not jobs:
        print("No hut-watch jobs on cron-job.org.")
    for j in jobs:
        print(f"{j['title'][len(PREFIX):]:<45} {'on ' if j.get('enabled') else 'OFF'} "
              f"last: {ts(j.get('lastExecution'))} {STATUS.get(j.get('lastStatus'), j.get('lastStatus'))}"
              f" | next: {ts(j.get('nextExecution'))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--remove", action="store_true")
    a = ap.parse_args()

    try:
        if a.status:
            show(api_key(ask=False))
            return
        key = api_key(ask=True)
        existing = our_jobs(key)  # also checks the API key
        if a.remove:
            for j in existing:
                call("DELETE", f"{CRONJOB_API}/jobs/{j['jobId']}", key)
                print("deleted", j["title"])
            return
        save_key(key)

        gh_token = os.environ.get("HUTWATCH_DISPATCH_TOKEN", "").strip() or \
            getpass.getpass("GitHub fine-grained token (hidden): ").strip()
        if not gh_token:
            sys.exit("No GitHub token given.")
        check_token(gh_token)

        by_title = {j["title"]: j for j in existing}
        wanted = {t for t, *_ in JOBS}
        created = 0
        for title, wf, inputs, sched in JOBS:
            body = {"job": job_body(title, wf, inputs, sched, gh_token)}
            if title in by_title:
                call("PATCH", f"{CRONJOB_API}/jobs/{by_title[title]['jobId']}", key, body)
                print("updated", title)
            else:
                if created and created % 4 == 0:
                    time.sleep(61)  # cron-job.org allows 5 job creations per minute
                time.sleep(1.2)
                call("PUT", f"{CRONJOB_API}/jobs", key, body)
                created += 1
                print("created", title)
        for title, j in by_title.items():
            if title not in wanted:
                call("DELETE", f"{CRONJOB_API}/jobs/{j['jobId']}", key)
                print("deleted (no longer used)", title)
        print()
        show(key)
        print(f"\ncron-job.org emails you if a job fails 3 times in a row or gets disabled.")
    except ApiError as e:
        sys.exit(f"Failed: {e}")


if __name__ == "__main__":
    main()
