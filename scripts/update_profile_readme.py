#!/usr/bin/env python3
"""Refresh dynamic repository and language sections in the ns-matrix profile README."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

OWNER = "ns-matrix"
README = "README.md"
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "ns-matrix-profile-readme-refresh",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

def api_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))

def get_repos():
    repos = api_json(f"{API}/users/{OWNER}/repos?per_page=100&sort=updated&type=owner")
    return [
        repo for repo in repos
        if repo.get("name") != OWNER and not repo.get("fork", False)
        and not repo.get("archived", False)
    ]

def safe(text):
    return str(text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()

def recent_repositories(repos):
    recent = sorted(repos, key=lambda item: item.get("pushed_at") or item.get("updated_at") or "", reverse=True)[:6]
    rows = [
        "| Repository | Primary language | Last updated | Stars |",
        "|---|---|---:|---:|",
    ]
    for repo in recent:
        name = safe(repo["name"])
        url = repo.get("html_url", f"https://github.com/{OWNER}/{repo['name']}")
        language = safe(repo.get("language") or "—")
        pushed = repo.get("pushed_at") or repo.get("updated_at") or ""
        try:
            updated = datetime.fromisoformat(pushed.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            updated = "—"
        rows.append(f"| [{name}]({url}) | {language} | {updated} | {repo.get('stargazers_count', 0)} |")
    if not recent:
        return "_No public repositories were returned by the GitHub API._"
    return "\n".join(rows)

def tech_hub(repos):
    totals = {}
    language_repos = {}
    for repo in repos:
        try:
            languages = api_json(repo["languages_url"])
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
        for language, byte_count in languages.items():
            totals[language] = totals.get(language, 0) + int(byte_count)
            language_repos[language] = language_repos.get(language, 0) + 1

    total_bytes = sum(totals.values())
    if not total_bytes:
        return "_Language data is not available yet._"

    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]
    rows = [
        "| Language | Share of detected code | Repositories using it |",
        "|---|---:|---:|",
    ]
    for language, count in ranked:
        pct = count / total_bytes * 100
        rows.append(f"| {safe(language)} | {pct:.1f}% | {language_repos[language]} |")
    rows.append("")
    rows.append(f"_Computed from GitHub language-byte statistics for {len(repos)} non-fork, non-archived repositories returned by the API. This is code volume, not a measure of proficiency._")
    return "\n".join(rows)

def replace_section(readme, name, body):
    start = f"<!-- AUTO:{name}:START -->"
    end = f"<!-- AUTO:{name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(readme):
        raise ValueError(f"Could not find marker pair for {name}")
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", readme, count=1)

def main():
    repos = get_repos()
    with open(README, "r", encoding="utf-8") as file:
        readme = file.read()
    readme = replace_section(readme, "RECENT_REPOS", recent_repositories(repos))
    readme = replace_section(readme, "TECH_HUB", tech_hub(repos))
    with open(README, "w", encoding="utf-8", newline="\n") as file:
        file.write(readme)
    print(f"Updated README from {len(repos)} public non-fork, non-archived repositories.")

if __name__ == "__main__":
    main()
