# Watches your GitHub repos and announces CI failures and recoveries, new stars, and new issues and PRs from others.
# Uses the GitHub CLI's login (gh auth token), so no token is stored by Nestor.
import datetime
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from nestor.config import DATA_DIR
from nestor.spoken import spoken_name
API_URL = "https://api.github.com"
STATE_PATH = os.path.join(DATA_DIR, "github_state.json")
FAILED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}
MAIN_BRANCHES = {"main", "master"}
SEEN_ISSUES_KEPT = 50
log = logging.getLogger(__name__)

# Get the token of the GitHub CLI's login (None if gh isn't installed or isn't logged in)
def gh_token():
    # gh missing or hanging means no GitHub alerts
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else None

# Load what was seen last time (stars, CI results, issues), or an empty state
def read_state():
    # First run: nothing seen yet
    if not os.path.exists(STATE_PATH):
        return {"stars": {}, "ci": {}, "issues": {}}
    with open(STATE_PATH, encoding="utf-8") as state_file:
        return json.load(state_file)

# Save what has been seen, so a restart doesn't announce old news
def write_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=1)

# Current time in GitHub's timestamp format
def utc_now_text():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Checks every few minutes and passes what changed to the announcer as alerts
class GitHubWatcher:
    # Set up and start checking in the background
    def __init__(self, announcer, settings):
        self.announcer = announcer
        self.settings = settings
        self.poll_seconds = max(60, float(settings.get("github_poll_minutes", 5)) * 60)
        self.token = gh_token()
        self.login = None
        self.state = read_state()
        threading.Thread(target=self.run, name="github", daemon=True).start()

    # Call the GitHub API and return the decoded JSON
    def get(self, path):
        api_request = urllib.request.Request(API_URL + path, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nestor"})
        with urllib.request.urlopen(api_request, timeout=20) as response:
            return json.load(response)

    # Background loop: check, announce, wait, repeat
    def run(self):
        # Without a gh login there is nothing to watch
        if not self.token:
            log.warning("GitHub alerts are off: log in with 'gh auth login' first")
            return

        # Runs for the life of the program; a failed check (e.g. no internet) is retried next time
        while True:
            # Report problems but keep watching
            try:
                self.check_all()
            except Exception as error:
                log.warning("GitHub check failed: %s", error)
            time.sleep(self.poll_seconds)

    # One full check of all your repos
    def check_all(self):
        # Learn which account is ours, once
        if not self.login:
            self.login = self.get("/user")["login"]
        repos = [repo for repo in self.get("/user/repos?affiliation=owner&per_page=100") if not repo["archived"]]
        messages = self.check_stars(repos) + self.check_ci(repos) + self.check_issues(repos)
        write_state(self.state)

        # Each change becomes an alert (held overnight during quiet hours)
        for message in messages:
            log.info("GitHub: %s", message)
            self.announcer.alert(message)

    # Announce repos whose star count went up
    def check_stars(self, repos):
        messages = []

        # Compare each repo's stars with last time
        for repo in repos:
            full_name = repo["full_name"]
            stars = repo["stargazers_count"]
            previous = self.state["stars"].get(full_name)

            # New repos are recorded silently; only increases are news
            if previous is not None and stars > previous:
                gained = stars - previous
                gained_words = "a new star" if gained == 1 else f"{gained} new stars"
                messages.append(f"{spoken_name(repo['name'], self.settings)} got {gained_words}. "
                                f"That's {stars} in total.")
            self.state["stars"][full_name] = stars
        return messages

    # Announce CI runs that failed, and checks that pass again after failing
    def check_ci(self, repos):
        messages = []

        # Look at the latest finished runs of each repo
        for repo in repos:
            runs = self.get(f"/repos/{repo['full_name']}/actions/runs?status=completed&per_page=30")["workflow_runs"]
            latest_runs = {}

            # Runs come newest first, so the first one per workflow and branch is the latest
            for run in runs:
                latest_runs.setdefault((run["name"], run["head_branch"]), run)

            # Compare each workflow and branch with what was seen last time
            for (workflow, branch), run in latest_runs.items():
                key = f"{repo['full_name']}|{workflow}|{branch}"
                previous = self.state["ci"].get(key)
                conclusion = run["conclusion"]
                failed_before = previous is not None and previous["conclusion"] in FAILED_CONCLUSIONS

                # Nothing new since last time
                if previous is not None and previous["run_id"] == run["id"]:
                    continue
                repo_words = spoken_name(repo["name"], self.settings)
                branch_words = "" if branch in MAIN_BRANCHES else f", on branch {spoken_name(branch, self.settings)}"

                # First sight is recorded silently; after that, failures and recoveries are news
                if previous is not None and conclusion in FAILED_CONCLUSIONS:
                    messages.append(f"The {workflow} check failed on {repo_words}{branch_words}.")
                elif conclusion == "success" and failed_before:
                    messages.append(f"The {workflow} check on {repo_words}{branch_words} is passing again.")

                # Cancelled and skipped runs don't count as passing or failing
                if conclusion in FAILED_CONCLUSIONS or conclusion == "success" or previous is None:
                    self.state["ci"][key] = {"run_id": run["id"], "conclusion": conclusion}
                else:
                    self.state["ci"][key] = {"run_id": run["id"], "conclusion": previous["conclusion"]}
        return messages

    # Announce issues and pull requests that other people opened since the last check
    def check_issues(self, repos):
        messages = []
        checked_at = utc_now_text()

        # Look at the newest issues and PRs of each repo
        for repo in repos:
            seen = self.state["issues"].get(repo["full_name"])
            items = self.get(f"/repos/{repo['full_name']}/issues?state=all&sort=created&direction=desc&per_page=10")

            # First sight of a repo: remember what's there without announcing it
            if seen is None:
                self.state["issues"][repo["full_name"]] = {"since": checked_at, "ids": [item["id"] for item in items]}
                continue

            # Announce each new item from a person other than you
            for item in items:
                is_new = item["created_at"] >= seen["since"]
                by_someone_else = item["user"]["login"] != self.login and item["user"]["type"] != "Bot"

                # Skip old, already announced, your own, and bot items
                if item["id"] in seen["ids"] or not is_new or not by_someone_else:
                    continue
                kind = "pull request" if "pull_request" in item else "issue"
                messages.append(f"New {kind} on {spoken_name(repo['name'], self.settings)} from "
                                f"{item['user']['login']}: {item['title'][:100]}")
                seen["ids"].append(item["id"])
            seen["ids"] = seen["ids"][-SEEN_ISSUES_KEPT:]
            seen["since"] = checked_at
        return messages
