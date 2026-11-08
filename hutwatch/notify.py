"""Alert channels: GitHub issues (record), ntfy.sh (fast push), Telegram (optional).

GitHub issue delivery failures raise, so the caller can keep the event pending and
fail the run. ntfy/Telegram failures are recorded in `errors` (run exits non-zero)
but never block the issue record.
"""

from __future__ import annotations

import os
import sys

from . import http
from .redact import ScrubList, scrub

GITHUB_API = "https://api.github.com"


class Notifier:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
        self.tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
        self.ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        self.errors: list[str] = ScrubList()
        self._open_issues: dict[str, int] | None = None
        # Issues need a token; HUTWATCH_ISSUES=off (e.g. the Mac launchd job, or a public repo
        # that wants alerts on ntfy only) logs them instead. ntfy/Telegram still send.
        self.issues_on = bool(self.token and self.repo) and os.environ.get("HUTWATCH_ISSUES", "on") != "off"
        if not dry_run and not self.issues_on:
            print("NOTE: GitHub issues disabled; issue alerts are only logged", file=sys.stderr)

    # ---------------- GitHub issues ----------------
    def _gh(self, method: str, path: str, body=None, params=None):
        r = http.request(
            method,
            f"{GITHUB_API}{path}",
            params=params,
            json_body=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        return r.json() if r.body else None

    def _issue_index(self) -> dict[str, int]:
        if self._open_issues is None:
            self._open_issues = {}
            for page in range(1, 4):
                items = self._gh("GET", f"/repos/{self.repo}/issues",
                                 params={"state": "open", "per_page": 100, "page": page}) or []
                for it in items:
                    if "pull_request" not in it:
                        self._open_issues.setdefault(it["title"], it["number"])
                if len(items) < 100:
                    break
        return self._open_issues

    def _cc(self) -> str:
        return f"\n\ncc @{self.owner}" if self.owner else ""

    def issue(self, title: str, body: str, *, comment_only: bool = False) -> str | None:
        """Comment on the open issue with this exact title, else open one.

        comment_only: do nothing if no open issue exists (used for 'recovered' notes).
        Returns the issue/comment URL. Raises http.FetchError on failure.
        """
        title, body = scrub(title), scrub(body[:60_000] + self._cc())
        if self.dry_run:
            print(f"\n=== [issue{' comment' if comment_only else ''}] {title}\n{body}\n")
            return None
        if not self.issues_on:
            # Logs of a public repo are public: record that an alert happened, not its content.
            print(f"[issue alert not posted: issues off] {title}")
            return None
        idx = self._issue_index()
        if title in idx:
            res = self._gh("POST", f"/repos/{self.repo}/issues/{idx[title]}/comments", {"body": body})
            return res.get("html_url") if res else None
        if comment_only:
            return None
        res = self._gh("POST", f"/repos/{self.repo}/issues", {"title": title, "body": body})
        idx[title] = res["number"]
        return res.get("html_url")

    # ---------------- Telegram ----------------
    def telegram(self, text: str) -> None:
        if not (self.tg_token and self.tg_chat):
            return
        if self.dry_run:
            print(f"=== [telegram] {text[:300]}")
            return
        try:
            http.request(
                "POST",
                f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                json_body={"chat_id": self.tg_chat, "text": text[:4000], "disable_web_page_preview": True},
            )
        except Exception as e:  # noqa: BLE001
            # Never echo the message: the URL contains the bot token.
            self.errors.append(f"telegram failed: {type(e.__cause__ or e).__name__}")

    # ---------------- ntfy.sh ----------------
    def ntfy(self, title: str, message: str, *, priority: int = 4, click: str | None = None,
             phone: str | None = None, tags: list[str] | None = None) -> bool:
        """Send one push. Returns True if ntfy accepted it (or dry run)."""
        if not self.ntfy_topic:
            print("WARNING: NTFY_TOPIC not set; skipping push", file=sys.stderr)
            return False
        actions = []
        if click:
            actions.append({"action": "view", "label": "Booking page", "url": click})
        if phone:
            actions.append({"action": "view", "label": f"Call {phone}", "url": "tel:" + "".join(
                ch for ch in phone if ch.isdigit() or ch == "+")})
        payload = {"topic": self.ntfy_topic, "title": title, "message": message[:3500],
                   "priority": priority, "tags": tags or []}
        if click:
            payload["click"] = click
        if actions:
            payload["actions"] = actions
        if self.dry_run:
            print(f"=== [ntfy p{priority}] {title}: {message[:300]} (click={click})")
            return True
        try:
            http.request("POST", self.ntfy_server + "/", json_body=payload)
            return True
        except Exception as e:  # noqa: BLE001
            # The topic is the secret: it is only ever sent in the JSON body, never logged.
            self.errors.append(f"ntfy failed: {e}".replace(self.ntfy_topic, "<topic>"))
            return False

    def issue_exists(self, title: str) -> bool:
        """An open issue with this title exists (used as a cross-workflow 'already alerted' lock)."""
        if self.dry_run or not self.issues_on:
            return False
        try:
            return title in self._issue_index()
        except Exception:  # noqa: BLE001
            return False
