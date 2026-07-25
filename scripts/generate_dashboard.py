import os
import sys
import json
import yaml
import requests
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_WIDTH = 8.4
LABEL_WIDTH = 13

ASCII_FONT_SIZE = 10
ASCII_CHAR_WIDTH = 6.0
ASCII_LINE_HEIGHT = 12

SVG_W = 800
PAD_TOP = 40
ASCII_PAD_LEFT = 15
RIGHT_X = 380
INFO_PAD_LEFT = RIGHT_X


def load_config():
    with open(ROOT_DIR / "profile.yml") as f:
        return yaml.safe_load(f)


def load_ascii_art():
    art_path = ROOT_DIR / "ascii"
    all_lines = []
    for fpath in sorted(art_path.glob("*.txt")):
        with open(fpath) as f:
            file_lines = [l.rstrip("\n") for l in f.readlines()]
        while file_lines and not file_lines[-1].strip():
            file_lines.pop()
        if all_lines:
            all_lines.append("")
        all_lines.extend(file_lines)
    return all_lines


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


def fetch_github_stats_graphql(username, token):
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
            "contributions": cc["contributionCalendar"]["totalContributions"],
        }
    except Exception as e:
        print(f"WARN: GraphQL API failed: {e}")
        return None


def fetch_github_stats_rest(username):
    try:
        r = requests.get(f"https://api.github.com/users/{username}", timeout=30)
        r.raise_for_status()
        data = r.json()
        repos_count = data.get("public_repos", 0)
        followers = data.get("followers", 0)

        stars = 0
        page = 1
        while page <= 5:
            rr = requests.get(
                f"https://api.github.com/users/{username}/repos?per_page=100&page={page}&type=owner",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=30,
            )
            if rr.status_code != 200 or not rr.json():
                break
            for repo in rr.json():
                stars += repo.get("stargazers_count", 0)
            page += 1

        return {
            "repos": repos_count,
            "stars": stars,
            "followers": followers,
            "contributions": 0,
        }
    except Exception as e:
        print(f"WARN: REST API failed: {e}")
        return None


def fetch_github_stats(username, token):
    if token:
        print("[*] Fetching stats via GraphQL...")
        stats = fetch_github_stats_graphql(username, token)
        if stats:
            return stats
        print("WARN: GraphQL failed, falling back to REST")

    print("[*] Fetching stats via public REST API...")
    stats = fetch_github_stats_rest(username)
    if stats:
        return stats

    print("WARN: All API methods failed, using fallback stats")
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
def generate_svg(config, stats, ascii_lines, theme="dark"):
    is_dark = theme == "dark"

    C = {
        "bg":      "#19171c" if is_dark else "#f2f1f5",
        "fg":      "#8b8792" if is_dark else "#4a4950",   # text
        "dim":     "#29262e" if is_dark else "#c4c2cd",   # Line under title
        "label":   "#7090b0" if is_dark else "#7090b0",   # Section title
        "title":   "#8c72b0" if is_dark else "#8c72b0",   # Top title
        "border":  "#29262e" if is_dark else "#c4c2cd",
        "art":     "#8b8792" if is_dark else "#4a4950",   # ascii
    }

    username = config["username"]
    hostname = config["hostname"]

    s = stats or {}
    repos = s.get("repos", 0)
    stars = s.get("stars", 0)
    followers = s.get("followers", 0)

    svg_parts = []

    # ── ASCII Art (left panel) ──
    if ascii_lines:
        for i, line in enumerate(ascii_lines):
            y = PAD_TOP + i * ASCII_LINE_HEIGHT
            svg_parts.append(
                f'    <text x="{ASCII_PAD_LEFT}" y="{y}" class="ascii" '
                f'xml:space="preserve">{xml_esc(line)}</text>'
            )

    # ── Vertical separator ──
    art_h = len(ascii_lines) * ASCII_LINE_HEIGHT if ascii_lines else 0
    sep_x = RIGHT_X - 15
    svg_parts.append(
        f'    <line x1="{sep_x}" y1="12" x2="{sep_x}" y2="{art_h + PAD_TOP + 8}" '
        f'stroke="{C["dim"]}" stroke-width="1" stroke-dasharray="4,4" opacity="1"/>'
    )

    # ── Info Panel (right side) ──
    y = PAD_TOP

    def add_title(text):
        nonlocal y
        svg_parts.append(f'    <text x="{INFO_PAD_LEFT}" y="{y}" class="title">{xml_esc(text)}</text>')
        y += LINE_HEIGHT

    def add_separator(length):
        nonlocal y
        svg_parts.append(f'    <text x="{INFO_PAD_LEFT}" y="{y}" class="dim">{"─" * length}</text>')
        y += LINE_HEIGHT

    def add_field(label, value):
        nonlocal y
        padded = label.ljust(LABEL_WIDTH)
        svg_parts.append(
            f'    <text x="{INFO_PAD_LEFT}" y="{y}">'
            f'<tspan class="label">{xml_esc(padded)}</tspan>'
            f'<tspan class="val">{xml_esc(str(value))}</tspan></text>'
        )
        y += LINE_HEIGHT

    def add_field_multiline(label, values):
        nonlocal y
        padded = label.ljust(LABEL_WIDTH)
        svg_parts.append(
            f'    <text x="{INFO_PAD_LEFT}" y="{y}">'
            f'<tspan class="label">{xml_esc(padded)}</tspan>'
            f'<tspan class="val">{xml_esc(str(values[0]))}</tspan></text>'
        )
        y += LINE_HEIGHT
        indent = " " * LABEL_WIDTH
        for v in values[1:]:
            svg_parts.append(
                f'    <text x="{INFO_PAD_LEFT}" y="{y}">'
                f'<tspan class="label">{indent}</tspan>'
                f'<tspan class="val">{xml_esc(str(v))}</tspan></text>'
            )
            y += LINE_HEIGHT

    def add_links(label, items):
        nonlocal y
        padded = label.ljust(LABEL_WIDTH)
        parts = []
        for item in items:
            txt = item["label"] if isinstance(item, dict) else str(item)
            url = item.get("url", "") if isinstance(item, dict) else ""
            if url:
                parts.append(
                    f'<a href="{xml_esc(url)}" target="_blank">'
                    f'<tspan class="link" text-decoration="underline">{xml_esc(txt)}</tspan></a>'
                )
            else:
                parts.append(f'<tspan class="link" text-decoration="underline">{xml_esc(txt)}</tspan>')
        joined = " <tspan class=\"fg\">•</tspan> ".join(parts)
        svg_parts.append(
            f'    <text x="{INFO_PAD_LEFT}" y="{y}">'
            f'<tspan class="label">{xml_esc(padded)}</tspan>{joined}</text>'
        )
        y += LINE_HEIGHT

    def add_spacer():
        nonlocal y
        y += LINE_HEIGHT

    # ── Build info content ──
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
    ])
    add_spacer()

    links = config.get("links", [])
    if links:
        add_links("Links", links)

    # ── Dynamic height ──
    info_h = y + 20
    art_h_total = PAD_TOP + len(ascii_lines) * ASCII_LINE_HEIGHT + 20 if ascii_lines else 0
    svg_h = max(info_h, art_h_total)

    # ── Assemble SVG ──
    svg = f"""<svg width="{SVG_W}" height="{svg_h}" viewBox="0 0 {SVG_W} {svg_h}"
     xmlns="http://www.w3.org/2000/svg">
  <style>
    .bg {{ fill: {C["bg"]}; stroke: {C["border"]}; stroke-width: 1; rx: 8; ry: 8; }}
    text {{ font-family: 'JetBrains Mono','Cascadia Code','Fira Code','SF Mono','Consolas','Courier New',monospace;
           font-size: {FONT_SIZE}px; fill: {C["fg"]}; white-space: pre; }}
    .ascii {{ font-size: {ASCII_FONT_SIZE}px; fill: {C["art"]}; }}
    .label {{ fill: {C["label"]}; font-weight: bold; }}
    .title {{ fill: {C["title"]}; font-weight: bold; }}
    .val {{ font-weight: bold; }}
    .dim {{ fill: {C["dim"]}; }}
    .link {{ fill: {C["fg"]}; font-weight: bold; }}
  </style>

  <rect class="bg" x="0.5" y="0.5" width="{SVG_W - 1}" height="{svg_h - 1}" />
{chr(10).join(svg_parts)}
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

    ascii_lines = load_ascii_art()
    print(f"[*] Loaded {len(ascii_lines)} lines of ASCII art")

    stats = fetch_github_stats(api_user, token)
    cache_path = ROOT_DIR / ".stats-cache.json"
    if stats:
        print(f"[*] Stats: {stats}")
        cache_path.write_text(json.dumps(stats, indent=2))
    elif cache_path.exists():
        stats = json.loads(cache_path.read_text())
        print("[*] Using cached stats")
    else:
        stats = {"repos": 0, "stars": 0, "followers": 0}

    for theme in ["dark", "light"]:
        svg = generate_svg(config, stats, ascii_lines, theme)
        if "<svg" not in svg or "</svg>" not in svg:
            print(f"ERROR: {theme} SVG invalid, skipping")
            continue
        out = ROOT_DIR / f"profile-{theme}.svg"
        out.write_text(svg)
        print(f"[✓] {out.name} ({len(svg):,} bytes)")

    print("[✓] Done!")


if __name__ == "__main__":
    main()
