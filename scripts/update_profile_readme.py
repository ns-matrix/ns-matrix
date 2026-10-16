#!/usr/bin/env python3
"""Refresh dynamic repository, language analytics and a text-only activity feed."""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime

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
        if repo.get("name") != OWNER
        and not repo.get("private", False)
        and not repo.get("fork", False)
        and not repo.get("archived", False)
    ]


def safe(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def parsed_date(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (ValueError, TypeError, AttributeError):
        return "—"


def repo_activity_date(repo):
    # The GitHub API sorts repos by updated; prefer a real push where available.
    return repo.get("pushed_at") or repo.get("created_at") or repo.get("updated_at") or ""


def recent_repositories(repos):
    # Keep active work near the top while ensuring newly created repos aren't lost.
    recent = sorted(repos, key=repo_activity_date, reverse=True)[:8]
    rows = [
        "| Repository | Language | Created | Latest push |",
        "|---|---|---:|---:|",
    ]
    for repo in recent:
        name = safe(repo["name"])
        url = repo.get("html_url", f"https://github.com/{OWNER}/{repo['name']}")
        language = safe(repo.get("language") or "—")
        created = parsed_date(repo.get("created_at"))
        pushed = parsed_date(repo.get("pushed_at"))
        rows.append(
            f"| [{name}]({url}) | {language} | {created} | {pushed} |"
        )
    return "\n".join(rows) if recent else "_No public repositories were returned by GitHub._"


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
        return "_GitHub language statistics are unavailable at the moment._"

    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]
    rows = [
        "| Language | Share | Visual distribution | Repositories |",
        "|---|---:|:---|---:|",
    ]
    for language, count in ranked:
        pct = count / total_bytes * 100
        blocks = min(20, max(1, round(pct / 5)))
        bar = "█" * blocks + "░" * (20 - blocks)
        rows.append(f"| {safe(language)} | {pct:.1f}% | `{bar}` | {language_repos[language]} |")
    rows.append("")
    rows.append(
        f"_Based on GitHub language-byte statistics for {len(repos)} public, non-fork, non-archived repositories. "
        "Code share is not a measure of developer proficiency._"
    )
    return "\n".join(rows)


def replace_section(readme, name, body):
    start = f"<!-- AUTO:{name}:START -->"
    end = f"<!-- AUTO:{name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(readme):
        raise ValueError(f"Missing README marker pair for {name}")
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
