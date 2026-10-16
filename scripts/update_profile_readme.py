#!/usr/bin/env python3
"""Refresh dynamic repository analytics, language pie chart, and newest-project card."""
import json
import html
import math
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
    """Most recently pushed repositories, excluding forks and archived repositories."""
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
        rows.append(f"| [{name}]({url}) | {language} | {created} | {pushed} |")
    return "\n".join(rows) if recent else "_No public repositories were returned by GitHub._"


def repo_readme_details(repo):
    """Extract a short summary and feature bullets from the repository's README."""
    branch = repo.get("default_branch") or "main"
    url = f"https://raw.githubusercontent.com/{OWNER}/{repo['name']}/{branch}/README.md"
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return "", []

    # Prefer a concise bold tagline or a short description paragraph.
    tagline = re.search(r"<strong>(.*?)</strong>", content, re.I | re.S)
    summary = ""
    if tagline:
        summary = re.sub(r"<[^>]+>", " ", tagline.group(1))
        summary = html.unescape(re.sub(r"\s+", " ", summary)).strip()
    if not summary:
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", content, re.I | re.S)
        for paragraph in paragraphs:
            plain = html.unescape(re.sub(r"<[^>]+>", " ", paragraph))
            plain = re.sub(r"\s+", " ", plain).strip()
            if len(plain) > 35 and not plain.lower().startswith(("project website", "source code", "report an issue")):
                summary = plain
                break
    if not summary:
        paragraphs = re.findall(r"(?m)^(?!#|>|\\[|\\s*$)(.{36,})$", content)
        if paragraphs:
            summary = re.sub(r"\s+", " ", paragraphs[0]).strip()

    # Pull concise feature bullets from a conventional "What it does" section.
    features = []
    match = re.search(
        r"(?is)^##\s+what it does\s*$([\s\S]*?)(?=^##\s+|\Z)",
        content,
        re.M,
    )
    if match:
        for line in match.group(1).splitlines():
            item = re.match(r"\s*[-*]\s+(.+)", line)
            if item:
                feature = html.unescape(re.sub(r"<[^>]+>", "", item.group(1))).strip()
                if feature:
                    features.append(re.sub(r"\s+", " ", feature))
            if len(features) >= 3:
                break
    return summary, features


def get_latest_created_project():
    """Fetch complete repository metadata, then select the newest-created eligible repo."""
    full_repos = []
    for repo in get_repos():
        try:
            detail = api_json(f"{API}/repos/{OWNER}/{repo['name']}")
            if not detail.get("private", False) and not detail.get("fork", False) and not detail.get("archived", False):
                full_repos.append(detail)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
    if not full_repos:
        return "_No public repositories were returned by GitHub._"
    newest = max(full_repos, key=lambda repo: repo.get("created_at") or "")
    name = safe(newest.get("name"))
    readme_summary, features = repo_readme_details(newest)
    description = safe(newest.get("description") or readme_summary or "Open the repository to explore its current code and implementation.")
    url = newest.get("html_url", f"https://github.com/{OWNER}/{newest['name']}")
    language = safe(newest.get("language") or "Not detected")
    created = parsed_date(newest.get("created_at"))
    pushed = parsed_date(newest.get("pushed_at"))
    feature_html = ""
    if features:
        feature_html = "<ul>" + "".join(f"<li>{html.escape(feature)}</li>" for feature in features) + "</ul>"
    return "\n".join([
        '<table width="100%" border="0" cellpadding="12" cellspacing="0">',
        '<tr><td>',
        '<p><b>🆕 LATEST REPOSITORY</b></p>',
        f'<h3><a href="{url}">🚀 {html.escape(name)}</a></h3>',
        f'<p>{html.escape(description)}</p>',
        feature_html,
        f'<p><b>Primary language:</b> {html.escape(language)} &nbsp; · &nbsp; <b>Created:</b> {created} &nbsp; · &nbsp; <b>Latest push:</b> {pushed}</p>',
        f'<p><a href="{url}">Explore the latest repository →</a></p>',
        '</td></tr></table>',
    ])


def make_pie_chart_svg(ranked, total_bytes):
    """Generate an SVG pie chart from live GitHub language-byte totals."""
    width, height = 760, 430
    cx, cy, radius = 245, 215, 145
    palette = [
        "#00F06A", "#00D9F5", "#BAFF66", "#7C83FD", "#FFB86C",
        "#FF6B9A", "#A78BFA", "#FDE047", "#67E8F9", "#FCA5A5",
    ]
    def point(angle):
        rad = math.radians(angle - 90)
        return cx + radius * math.cos(rad), cy + radius * math.sin(rad)

    paths = []
    angle = 0.0
    for idx, (language, count) in enumerate(ranked):
        share = count / total_bytes
        sweep = share * 360
        x1, y1 = point(angle)
        x2, y2 = point(angle + sweep)
        if sweep >= 359.999:
            # SVG needs two arcs to draw a full circle.
            xm, ym = point(angle + 180)
            d = f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 1 1 {xm:.2f} {ym:.2f} A {radius} {radius} 0 1 1 {x1:.2f} {y1:.2f} Z"
        else:
            large = 1 if sweep > 180 else 0
            d = f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large} 1 {x2:.2f} {y2:.2f} Z"
        paths.append(f'<path d="{d}" fill="{palette[idx % len(palette)]}" stroke="#07110B" stroke-width="2"><title>{safe(language)}: {share*100:.1f}%</title></path>')
        angle += sweep

    legend = []
    for idx, (language, count) in enumerate(ranked):
        y = 84 + idx * 31
        pct = count / total_bytes * 100
        legend.append(
            f'<rect x="455" y="{y-13}" width="14" height="14" rx="3" fill="{palette[idx % len(palette)]}"/>'
            f'<text x="480" y="{y}" fill="#E8FFF0" font-size="17">{safe(language)}</text>'
            f'<text x="720" y="{y}" text-anchor="end" fill="#BAFF66" font-size="17" font-weight="600">{pct:.1f}%</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" rx="18" fill="#050D09"/>'
        '<text x="32" y="38" fill="#00F06A" font-family="Segoe UI,Arial,sans-serif" font-size="22" font-weight="700">TECH HUB · CODE DISTRIBUTION</text>'
        '<text x="32" y="63" fill="#9CB7A4" font-family="Segoe UI,Arial,sans-serif" font-size="12">Share of detected language bytes</text>'
        + ''.join(paths) + ''.join(legend)
        + '<text x="32" y="405" fill="#9CB7A4" font-family="Segoe UI,Arial,sans-serif" font-size="12">Repository language-byte totals · auto-generated by GitHub Actions</text>'
        + '</svg>'
    )
    return svg.encode("utf-8")


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
    # Generate a committed SVG asset; the workflow stages it with the README.
    svg_bytes = make_pie_chart_svg(ranked, total_bytes)
    os.makedirs("assets", exist_ok=True)
    with open("assets/tech-hub-pie.svg", "wb") as file:
        file.write(svg_bytes)

    rows = [
        '<div align="center">',
        '<img src="https://raw.githubusercontent.com/ns-matrix/ns-matrix/main/assets/tech-hub-pie.svg" width="100%" alt="Auto-generated pie chart of GitHub language-byte distribution" />',
        '</div>',
        '',
        '| Language | Share | Repositories |',
        '|---|---:|---:|',
    ]
    for language, count in ranked:
        pct = count / total_bytes * 100
        rows.append(f"| {safe(language)} | {pct:.1f}% | {language_repos[language]} |")
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
    readme = replace_section(readme, "LATEST_PROJECT", get_latest_created_project())
    readme = replace_section(readme, "TECH_HUB", tech_hub(repos))

    with open(README, "w", encoding="utf-8", newline="\n") as file:
        file.write(readme)
    print(f"Updated README from {len(repos)} public non-fork, non-archived repositories.")


if __name__ == "__main__":
    main()
