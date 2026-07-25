import os
import sys
import json
import yaml
import requests
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_WIDTH = 8.4
LABEL_WIDTH = 13

SVG_W = 520
PAD_TOP = 40
PAD_LEFT = 30


def load_config():
    with open(ROOT_DIR / "profile.yml") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────
# GitHub API
# ──────────────────────────────────────────────
GRAPHQL_URL = "https://api.github.com/graphql"
STATS_QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
      totalCount
      nodes { stargazerCount }
    }
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar { totalContributions }
    }
  }
}
"""


def fetch_github_stats(username, token):
    if not token:
        print("WARN: No GITHUB_TOKEN, using fallback stats")
        return None
    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(GRAPHQL_URL,
                             json={"query": STATS_QUERY, "variables": {"login": username}},
                             headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            print(f"WARN: GraphQL errors: {data['errors']}")
            return None
        user = data["data"]["user"]
        repos = user["repositories"]
        cc = user["contributionsCollection"]
        return {
            "repos": repos["totalCount"],
            "stars": sum(n["stargazerCount"] for n in repos["nodes"]),
            "followers": user["followers"]["totalCount"],
            "commits": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
            "contributions": cc["contributionCalendar"]["totalContributions"],
        }
    except Exception as e:
        print(f"WARN: GitHub API failed: {e}")
        return None


def xml_esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:,}"


# ──────────────────────────────────────────────
# SVG Generation
# ──────────────────────────────────────────────
def generate_svg(config, stats, theme="dark"):
    is_dark = theme == "dark"

    C = {
        "bg":     "#0d1117" if is_dark else "#ffffff",
        "fg":     "#c9d1d9" if is_dark else "#24292f",
        "dim":    "#8b949e" if is_dark else "#57606a",
        "label":  "#79c0ff" if is_dark else "#0550ae",
        "title":  "#58a6ff" if is_dark else "#0969da",
        "border": "#30363d" if is_dark else "#d0d7de",
    }

    username = config["username"]
    hostname = config["hostname"]

    s = stats or {}
    repos = s.get("repos", 0)
    stars = s.get("stars", 0)
    followers = s.get("followers", 0)
    commits = s.get("commits", 0)

    lines = []
    y = PAD_TOP

    def add_title(text):
        nonlocal y
        lines.append(f'    <text x="{PAD_LEFT}" y="{y}" class="title">{xml_esc(text)}</text>')
        y += LINE_HEIGHT

    def add_separator(length):
        nonlocal y
        lines.append(f'    <text x="{PAD_LEFT}" y="{y}" class="dim">{"─" * length}</text>')
        y += LINE_HEIGHT

    def add_field(label, value):
        nonlocal y
        padded = label.ljust(LABEL_WIDTH)
        lines.append(
            f'    <text x="{PAD_LEFT}" y="{y}">'
            f'<tspan class="label">{xml_esc(padded)}</tspan>'
            f'<tspan class="val">{xml_esc(str(value))}</tspan></text>'
        )
        y += LINE_HEIGHT

    def add_field_multiline(label, values):
        nonlocal y
        padded = label.ljust(LABEL_WIDTH)
        lines.append(
            f'    <text x="{PAD_LEFT}" y="{y}">'
            f'<tspan class="label">{xml_esc(padded)}</tspan>'
            f'<tspan class="val">{xml_esc(str(values[0]))}</tspan></text>'
        )
        y += LINE_HEIGHT
        indent = " " * LABEL_WIDTH
        for v in values[1:]:
            lines.append(
                f'    <text x="{PAD_LEFT}" y="{y}">'
                f'<tspan class="label">{indent}</tspan>'
                f'<tspan class="val">{xml_esc(str(v))}</tspan></text>'
            )
            y += LINE_HEIGHT

    def add_spacer():
        nonlocal y
        y += LINE_HEIGHT

    # ── Build content ──
    add_title(f"{username}@{hostname}")
    add_separator(50)
    add_spacer()

    add_field("Role", config.get("role", ""))
    add_field("Location", config.get("location", ""))
    add_field("Focus", config.get("focus", ""))
    add_spacer()

    add_field("Languages", config.get("languages", ""))
    add_spacer()

    add_field("OS", config.get("os", ""))
    add_field("Learning", config.get("learning", ""))
    add_spacer()

    add_field_multiline("GitHub", [
        f"{fmt(repos)} repositories",
        f"{fmt(stars)} stars",
        f"{fmt(followers)} followers",
        f"{fmt(commits)} commits",
    ])
    add_spacer()

    links = config.get("links", [])
    if links:
        link_labels = [l["label"] if isinstance(l, dict) else str(l) for l in links]
        add_field_multiline("Links", link_labels)

    # ── Assemble SVG ──
    svg_h = y + 20

    svg = f"""<svg width="{SVG_W}" height="{svg_h}" viewBox="0 0 {SVG_W} {svg_h}"
     xmlns="http://www.w3.org/2000/svg">
  <style>
    .bg {{ fill: {C["bg"]}; stroke: {C["border"]}; stroke-width: 1; rx: 8; ry: 8; }}
    text {{ font-family: 'JetBrains Mono','Cascadia Code','Fira Code','SF Mono','Consolas','Courier New',monospace;
           font-size: {FONT_SIZE}px; fill: {C["fg"]}; white-space: pre; }}
    .label {{ fill: {C["label"]}; font-weight: bold; }}
    .title {{ fill: {C["title"]}; font-weight: bold; }}
    .val {{ font-weight: bold; }}
    .dim {{ fill: {C["dim"]}; }}
  </style>

  <rect class="bg" x="0.5" y="0.5" width="{SVG_W - 1}" height="{svg_h - 1}" />

{chr(10).join(lines)}
</svg>"""
    return svg


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    config = load_config()
    token = os.environ.get("GITHUB_TOKEN", "")
    username = config["username"]
    api_user = config.get("github_username", username)

    print(f"[*] Generating dashboard for {api_user} (display: {username})")

    stats = fetch_github_stats(api_user, token)
    cache_path = ROOT_DIR / ".stats-cache.json"
    if stats:
        print(f"[*] Stats: {stats}")
        cache_path.write_text(json.dumps(stats, indent=2))
    elif cache_path.exists():
        stats = json.loads(cache_path.read_text())
        print("[*] Using cached stats")
    else:
        stats = {"repos": 0, "stars": 0, "followers": 0, "commits": 0, "contributions": 0}

    for theme in ["dark", "light"]:
        svg = generate_svg(config, stats, theme)
        if "<svg" not in svg or "</svg>" not in svg:
            print(f"ERROR: {theme} SVG invalid, skipping")
            continue
        out = ROOT_DIR / f"profile-{theme}.svg"
        out.write_text(svg)
        print(f"[✓] {out.name} ({len(svg):,} bytes)")

    print("[✓] Done!")


if __name__ == "__main__":
    main()
