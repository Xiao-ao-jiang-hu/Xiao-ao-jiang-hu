import json
import math
import os
import time
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FOOTPRINT_SVG = ROOT / "assets" / "images" / "github-footprint.svg"
API_BASE = os.getenv("PROFILE_API_BASE", "https://xiaoaojianghu.fun").rstrip("/")
BLOG_URL = os.getenv("PROFILE_BLOG_FEED_URL", f"{API_BASE}/api/blog-feed/")
STATUS_URL = os.getenv("PROFILE_STATUS_URL", f"{API_BASE}/api/status/")
GITHUB_LOGIN = os.getenv("PROFILE_GITHUB_LOGIN", "Xiao-ao-jiang-hu")
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
INCLUDE_PRIVATE_REPOS = os.getenv("PROFILE_INCLUDE_PRIVATE_REPOS", "").lower() in {"1", "true", "yes"}
USER_AGENT = "xiaoaojianghu-profile-readme/1.0"
MAX_ATTEMPTS = int(os.getenv("PROFILE_FETCH_ATTEMPTS", "3"))


def with_retries(label, operation, max_attempts=MAX_ATTEMPTS):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            wait_seconds = 2 ** (attempt - 1)
            print(f"{label} failed on attempt {attempt}/{max_attempts}: {exc}; retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
    raise last_error


def fetch_json(url):
    def operation():
        request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"Network error while fetching {url}: {exc.reason}") from exc

    return with_retries(url, operation)


def fetch_github_graphql(query, variables=None):
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return None

    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = Request(
        GITHUB_GRAPHQL_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    def operation():
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub GraphQL network error: {exc.reason}") from exc

    payload = with_retries("GitHub GraphQL", operation)

    if payload.get("errors"):
        messages = "; ".join(error.get("message", "Unknown error") for error in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL error: {messages}")
    return payload.get("data")


def replace_between(text, start_marker, end_marker, replacement):
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return f"{text[:start]}\n{replacement.strip()}\n{text[end:]}"


def try_render(label, fetcher, renderer):
    try:
        return renderer(fetcher())
    except Exception as exc:
        print(f"Skipping {label}: {exc}")
        return None


def md_link_text(value):
    return str(value or "").replace("[", "\\[").replace("]", "\\]").strip()


def format_duration(seconds):
    seconds = int(seconds or 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} hrs {minutes} mins"
    if minutes:
        return f"{minutes} mins {seconds} secs"
    return f"{seconds} secs"


def format_percentage(value):
    return f"{value:.2f} %"


def compact_number(value):
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def hex_to_rgb(color):
    color = (color or "#3b82f6").strip().lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    try:
        return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return (59, 130, 246)


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in rgb)


def lerp_color(start, end, amount):
    start_rgb = hex_to_rgb(start)
    end_rgb = hex_to_rgb(end)
    return rgb_to_hex(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * amount for index in range(3))


def gradient_color(amount):
    colors = ["#ad2f86", "#6f3fc9", "#2563eb", "#14b8a6", "#22c55e", "#eab308", "#ef4444"]
    amount = max(0.0, min(1.0, amount))
    scaled = amount * (len(colors) - 1)
    index = min(int(scaled), len(colors) - 2)
    return lerp_color(colors[index], colors[index + 1], scaled - index)


def polar_point(cx, cy, radius, angle_degrees):
    angle = math.radians(angle_degrees)
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def donut_segment_path(cx, cy, inner_radius, outer_radius, start_degrees, end_degrees):
    large_arc = 1 if end_degrees - start_degrees > 180 else 0
    outer_start = polar_point(cx, cy, outer_radius, start_degrees)
    outer_end = polar_point(cx, cy, outer_radius, end_degrees)
    inner_end = polar_point(cx, cy, inner_radius, end_degrees)
    inner_start = polar_point(cx, cy, inner_radius, start_degrees)
    return (
        f"M {outer_start[0]:.2f} {outer_start[1]:.2f} "
        f"A {outer_radius} {outer_radius} 0 {large_arc} 1 {outer_end[0]:.2f} {outer_end[1]:.2f} "
        f"L {inner_end[0]:.2f} {inner_end[1]:.2f} "
        f"A {inner_radius} {inner_radius} 0 {large_arc} 0 {inner_start[0]:.2f} {inner_start[1]:.2f} Z"
    )


def build_bar_line(label, seconds, total_seconds, width=25):
    if total_seconds <= 0:
        percent = 0.0
    else:
        percent = (seconds / total_seconds) * 100
    filled = int(round((percent / 100) * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"{label:<24} {format_duration(seconds):<18} {bar}   {format_percentage(percent)}"


def build_count_bar_line(label, value, max_value, width=25):
    value = int(value or 0)
    max_value = max(int(max_value or 0), 1)
    percent = value / max_value * 100
    filled = int(round((percent / 100) * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"{label:<24} {value:<18} {bar}   {format_percentage(percent)}"


def render_blog(payload):
    posts = payload.get("posts") or []
    if not posts:
        error = payload.get("error") or "No posts returned from blog API."
        return f"- {error}"

    lines = []
    for post in posts[:5]:
        url = post.get("url") or "https://blog.xiaoaojianghu.fun"
        date_text = md_link_text(post.get("date") or "")
        title = md_link_text(post.get("title") or "Untitled")
        prefix = f"**{date_text}** - " if date_text else ""
        lines.append(f"- {prefix}[{title}]({url})")
    return "\n".join(lines)


def render_wakatime(payload):
    wakatime = payload.get("wakatime")
    if not wakatime:
        error = payload.get("wakatime_error") or "No WakaTime data returned from status API."
        return f"- {error}"

    total_seconds = int(wakatime.get("range_total_seconds") or 0)
    daily = wakatime.get("daily") or []
    range_days = wakatime.get("range_days") or len(daily)
    range_start = wakatime.get("range_start") or ""
    range_end = wakatime.get("range_end") or ""
    languages = [item for item in wakatime.get("languages") or [] if int(item.get("seconds") or 0) > 0][:5]
    editors = [item for item in wakatime.get("editors") or [] if int(item.get("seconds") or 0) > 0][:5]
    operating_systems = [item for item in wakatime.get("operating_systems") or [] if int(item.get("seconds") or 0) > 0][:3]

    if not operating_systems and total_seconds > 0:
        operating_systems = [{"name": "Unknown", "seconds": total_seconds}]

    lines = [
        f"🕑 Time Zone: Asia/Shanghai",
        "",
        "💬 Programming Languages:",
    ]

    if languages:
        for item in languages:
            lines.append(build_bar_line(md_link_text(item.get("name") or "Unknown"), int(item.get("seconds") or 0), total_seconds))
    else:
        lines.append("No language data available.")

    lines.extend(
        [
            "",
            "🔥 Editors:",
        ]
    )
    if editors:
        for item in editors:
            lines.append(build_bar_line(md_link_text(item.get("name") or "Unknown"), int(item.get("seconds") or 0), total_seconds))
    else:
        lines.append("No editor data available.")

    lines.extend(
        [
            "",
            "💻 Operating Systems:",
        ]
    )
    if operating_systems:
        for item in operating_systems:
            lines.append(build_bar_line(md_link_text(item.get("name") or "Unknown"), int(item.get("seconds") or 0), total_seconds))
    else:
        lines.append("No operating system data available.")

    return "\n".join(
        [
            "**This Week I Spent My Time On**",
            "",
            "```text",
            *lines,
            "```",
            "",
            f"Range: {range_start} -> {range_end}",
            f"Last {range_days} days total: {format_duration(total_seconds)}",
        ]
    )


def collect_repo_connection(field_name, query, login):
    repos = {}
    cursor = None

    while True:
        data = fetch_github_graphql(query, {"login": login, "cursor": cursor})
        if not data:
            return None

        user = data.get("user") or {}
        connection = user.get(field_name) or {}
        for repo in connection.get("nodes") or []:
            if not repo:
                continue
            repos[repo["nameWithOwner"]] = {
                "name": repo["nameWithOwner"],
                "stars": int(repo.get("stargazerCount") or 0),
                "forks": int(repo.get("forkCount") or 0),
                "is_fork": bool(repo.get("isFork")),
                "is_private": bool(repo.get("isPrivate")),
                "url": repo.get("url") or "",
                "language": (repo.get("primaryLanguage") or {}).get("name") or "Other",
                "language_color": (repo.get("primaryLanguage") or {}).get("color") or "#64748b",
            }

        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return repos
        cursor = page_info.get("endCursor")


def fetch_github_activity(login=GITHUB_LOGIN):
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return None

    today = date.today()
    start_date = today - timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                weekday
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    def operation():
        body = json.dumps(
            {
                "query": query,
                "variables": {
                    "login": login,
                    "from": f"{start_date.isoformat()}T00:00:00Z",
                    "to": f"{today.isoformat()}T23:59:59Z",
                },
            }
        ).encode("utf-8")
        request = Request(
            GITHUB_GRAPHQL_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"GitHub GraphQL network error: {exc.reason}") from exc
        if payload.get("errors"):
            messages = "; ".join(error.get("message", "Unknown error") for error in payload["errors"])
            raise RuntimeError(f"GitHub GraphQL error: {messages}")
        user = (payload.get("data") or {}).get("user") or {}
        contributions = user.get("contributionsCollection") or {}
        return {
            "activity": contributions,
        }

    return with_retries("GitHub GraphQL", operation)


def fetch_github_footprint(login=GITHUB_LOGIN):
    activity = fetch_github_activity(login)
    if activity is None:
        return None

    privacy_filter = "" if INCLUDE_PRIVATE_REPOS else "privacy: PUBLIC"
    contributed_query = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositoriesContributedTo(
          first: 100
          after: $cursor
          PRIVACY_FILTER
          includeUserRepositories: true
          contributionTypes: [COMMIT]
          orderBy: {field: STARGAZERS, direction: DESC}
        ) {
          nodes {
            nameWithOwner
            stargazerCount
            forkCount
            isFork
            isPrivate
            url
            primaryLanguage {
              name
              color
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """.replace("PRIVACY_FILTER", privacy_filter)

    contributed = collect_repo_connection("repositoriesContributedTo", contributed_query, login)
    if contributed is None:
        return None

    repos = {**contributed}
    participating_repos = list(repos.values())
    participating_repos.sort(key=lambda item: (item["stars"], item["forks"], item["name"]), reverse=True)

    return {
        "includes_private": INCLUDE_PRIVATE_REPOS,
        "repo_count": len(participating_repos),
        "stars": sum(repo["stars"] for repo in participating_repos),
        "forks": sum(repo["forks"] for repo in participating_repos),
        "repos": participating_repos,
        "activity": activity["activity"],
    }


def render_clean_footprint_svg(payload):
    activity = payload.get("activity") or {}
    calendar = activity.get("contributionCalendar") or {}
    weeks = calendar.get("weeks") or []
    days = [day for week in weeks for day in (week.get("contributionDays") or [])]
    max_day = max((int(day.get("contributionCount") or 0) for day in days), default=1)
    total_contributions = int(calendar.get("totalContributions") or 0)
    repo_count = int(payload.get("repo_count") or 0)
    stars = int(payload.get("stars") or 0)
    forks = int(payload.get("forks") or 0)
    commit_total = int(activity.get("totalCommitContributions") or 0)
    issue_total = int(activity.get("totalIssueContributions") or 0)
    pr_total = int(activity.get("totalPullRequestContributions") or 0)
    review_total = int(activity.get("totalPullRequestReviewContributions") or 0)
    repo_total = int(activity.get("totalRepositoryContributions") or 0)
    start_text = days[0].get("date") if days else ""
    end_text = days[-1].get("date") if days else ""

    language_counts = {}
    language_colors = {}
    for repo in payload.get("repos") or []:
        language = repo.get("language") or "Other"
        language_counts[language] = language_counts.get(language, 0) + 1
        language_colors.setdefault(language, repo.get("language_color") or "#64748b")
    sorted_languages = sorted(
        ((language, count) for language, count in language_counts.items() if language != "Other"),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )
    top_languages = sorted_languages[:4]
    other_count = language_counts.get("Other", 0) + sum(count for _, count in sorted_languages[4:])
    if other_count:
        top_languages.append(("Other", other_count))
    if not top_languages:
        top_languages = [("Other", 1)]
        language_colors["Other"] = "#64748b"

    def diamond(cx, cy, width=13, height=7):
        return f"{cx},{cy - height} {cx + width},{cy} {cx},{cy + height} {cx - width},{cy}"

    week_count = max(len(weeks), 1)
    tiles = []
    for week_index, week in enumerate(weeks):
        for day_index, day in enumerate(week.get("contributionDays") or []):
            count = int(day.get("contributionCount") or 0)
            amount = count / max_day if max_day else 0
            base_color = gradient_color(week_index / max(week_count - 1, 1))
            top_color = lerp_color("#172033", base_color, 0.16 + 0.84 * amount)
            left_color = lerp_color("#0f172a", base_color, 0.1 + 0.55 * amount)
            right_color = lerp_color("#0b1020", base_color, 0.08 + 0.42 * amount)
            cx = 128 + week_index * 15 + day_index * 8
            cy = 297 + week_index * 7 + day_index * 8
            height = 0 if count == 0 else int(8 + 54 * math.sqrt(amount))
            if height:
                left = f"{cx - 13},{cy} {cx},{cy + 7} {cx},{cy - height + 7} {cx - 13},{cy - height}"
                right = f"{cx + 13},{cy} {cx},{cy + 7} {cx},{cy - height + 7} {cx + 13},{cy - height}"
                tiles.append(
                    f'<g opacity="{0.28 + 0.72 * amount:.2f}">'
                    f'<polygon points="{left}" fill="{left_color}" />'
                    f'<polygon points="{right}" fill="{right_color}" />'
                    f'<polygon points="{diamond(cx, cy - height)}" fill="{top_color}" stroke="#020617" stroke-width="1" />'
                    f"</g>"
                )
            else:
                tiles.append(f'<polygon points="{diamond(cx, cy)}" fill="{top_color}" stroke="#020617" stroke-width="1" opacity="0.24" />')

    donut_x = 300
    donut_y = 760
    total_language_repos = max(sum(count for _, count in top_languages), 1)
    donut_segments = []
    start_angle = -90
    for language, count in top_languages:
        end_angle = start_angle + 360 * count / total_language_repos
        donut_segments.append(
            f'<path d="{donut_segment_path(donut_x, donut_y, 68, 130, start_angle, end_angle)}" fill="{language_colors.get(language, "#64748b")}" />'
        )
        start_angle = end_angle

    legend_items = []
    for index, (language, count) in enumerate(top_languages):
        color = language_colors.get(language, "#64748b")
        legend_items.append(
            f'<g transform="translate(440,{690 + index * 42})">'
            f'<rect width="22" height="22" fill="{color}" rx="2" />'
            f'<text x="34" y="18" fill="#f8fafc" font-size="24" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">{escape(language)}</text>'
            f'<text x="210" y="18" fill="#cbd5e1" font-size="22" text-anchor="end" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">{count}</text>'
            f"</g>"
        )

    radar = [("Commit", commit_total), ("Issue", issue_total), ("PullReq", pr_total), ("Review", review_total), ("Repo", repo_total)]
    radar_x = 1230
    radar_y = 360
    radar_r = 128
    radar_grid = []
    for level in range(1, 5):
        radius = radar_r * level / 4
        points = " ".join(
            f"{polar_point(radar_x, radar_y, radius, -90 + index * 72)[0]:.2f},{polar_point(radar_x, radar_y, radius, -90 + index * 72)[1]:.2f}"
            for index in range(5)
        )
        radar_grid.append(f'<polygon points="{points}" fill="none" stroke="#cbd5e1" stroke-dasharray="6 8" opacity="{0.25 + level * 0.12:.2f}" />')
    radar_points = " ".join(
        f"{polar_point(radar_x, radar_y, radar_r * min(1.0, math.log10(max(value, 0) + 1) / 4), -90 + index * 72)[0]:.2f},"
        f"{polar_point(radar_x, radar_y, radar_r * min(1.0, math.log10(max(value, 0) + 1) / 4), -90 + index * 72)[1]:.2f}"
        for index, (_, value) in enumerate(radar)
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1572 920" width="1572" height="920" role="img" aria-label="Contribution footprint">
  <defs>
    <linearGradient id="panel" x1="0" x2="1" y1="0" y2="1"><stop offset="0%" stop-color="#0b1220" /><stop offset="100%" stop-color="#09090f" /></linearGradient>
    <linearGradient id="glow" x1="0" x2="1"><stop offset="0%" stop-color="#ec4899" stop-opacity="0.16" /><stop offset="50%" stop-color="#22c55e" stop-opacity="0.18" /><stop offset="100%" stop-color="#3b82f6" stop-opacity="0.2" /></linearGradient>
    <filter id="softShadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#020617" flood-opacity="0.6" /></filter>
  </defs>
  <rect width="1572" height="920" fill="url(#panel)" />
  <rect x="20" y="20" width="1532" height="880" fill="none" stroke="url(#glow)" stroke-width="1" opacity="0.5" />
  <text x="60" y="82" fill="#f8fafc" font-size="36" font-weight="700" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">Contribution Footprint</text>
  <text x="1430" y="100" fill="#e2e8f0" font-size="22" text-anchor="end" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">{escape(start_text)} / {escape(end_text)}</text>
  <g transform="translate(420,128)">
    <rect width="130" height="52" fill="#525252" /><rect x="130" width="82" height="52" fill="#0ea5e9" /><rect x="230" width="140" height="52" fill="#525252" /><rect x="370" width="118" height="52" fill="#facc15" /><rect x="506" width="130" height="52" fill="#525252" /><rect x="636" width="94" height="52" fill="#38bdf8" />
    <text x="24" y="34" fill="#f8fafc" font-size="22" font-weight="700" letter-spacing="3" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">REPOS</text><text x="154" y="35" fill="#ffffff" font-size="26" font-weight="800" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">{repo_count}</text>
    <text x="253" y="34" fill="#f8fafc" font-size="22" font-weight="700" letter-spacing="3" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">STARS</text><text x="429" y="35" fill="#111827" font-size="26" font-weight="800" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">{compact_number(stars)}</text>
    <text x="529" y="34" fill="#f8fafc" font-size="22" font-weight="700" letter-spacing="3" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">FORKS</text><text x="683" y="35" fill="#ffffff" font-size="26" font-weight="800" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">{compact_number(forks)}</text>
  </g>
  <g filter="url(#softShadow)"><rect x="58" y="210" width="1456" height="545" rx="12" fill="#121926" /></g>
  <g>{"".join(tiles)}</g>
  <g>{"".join(radar_grid)}<line x1="1230" y1="232" x2="1230" y2="488" stroke="#cbd5e1" stroke-dasharray="6 8" opacity="0.35" /><line x1="1108" y1="320" x2="1352" y2="400" stroke="#cbd5e1" stroke-dasharray="6 8" opacity="0.35" /><line x1="1110" y1="400" x2="1350" y2="320" stroke="#cbd5e1" stroke-dasharray="6 8" opacity="0.35" /><polygon points="{radar_points}" fill="#facc15" fill-opacity="0.62" stroke="#fbbf24" stroke-width="4" />
    <text x="1230" y="206" fill="#f8fafc" font-size="28" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">Commit</text><text x="1382" y="360" fill="#f8fafc" font-size="28" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">Issue</text><text x="1320" y="545" fill="#f8fafc" font-size="28" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">PullReq</text><text x="1140" y="545" fill="#f8fafc" font-size="28" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">Review</text><text x="1080" y="360" fill="#f8fafc" font-size="28" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">Repo</text>
    <text x="1230" y="246" fill="#cbd5e1" font-size="18" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">10K</text><text x="1230" y="278" fill="#cbd5e1" font-size="18" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">1K</text><text x="1230" y="310" fill="#cbd5e1" font-size="18" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">100</text><text x="1230" y="342" fill="#cbd5e1" font-size="18" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">10</text>
  </g>
  <g>{"".join(donut_segments)}<circle cx="{donut_x}" cy="{donut_y}" r="68" fill="#09090f" /><text x="{donut_x}" y="{donut_y + 8}" fill="#f8fafc" font-size="30" text-anchor="middle" font-weight="700" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">{compact_number(total_language_repos)}</text><text x="{donut_x}" y="{donut_y + 38}" fill="#cbd5e1" font-size="18" text-anchor="middle" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">repos</text></g>
  {"".join(legend_items)}
  <g transform="translate(800,850)"><text x="0" y="0" fill="#fbbf24" font-size="42" font-weight="800" text-anchor="end" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">{compact_number(total_contributions)}</text><text x="12" y="0" fill="#f8fafc" font-size="24" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">contributions</text><text x="250" y="0" fill="#e2e8f0" font-size="34" font-weight="700" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">stars {compact_number(stars)}</text><text x="480" y="0" fill="#e2e8f0" font-size="34" font-weight="700" font-family="ui-monospace, SFMono-Regular, Consolas, monospace">forks {compact_number(forks)}</text></g>
  <text x="1110" y="885" fill="#cbd5e1" font-size="18" font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">commits {compact_number(commit_total)} · issues {compact_number(issue_total)} · pull requests {compact_number(pr_total)} · reviews {compact_number(review_total)}</text>
</svg>
"""
    FOOTPRINT_SVG.write_text(svg, encoding="utf-8", newline="\n")
    return f'<p align="center"><img width="100%" src="assets/images/github-footprint.svg" alt="GitHub contribution footprint" /></p>'


def render_footprint_svg(payload):
    if not payload:
        return None
    return render_clean_footprint_svg(payload)

def render_github_footprint(payload):
    if not payload:
        return "- Contribution footprint will be updated by GitHub Actions."

    return render_footprint_svg(payload)


def main():
    today = date.today()
    start_date = today - timedelta(days=29)
    status_query = urlencode({"start": start_date.isoformat(), "end": today.isoformat()})

    blog_section = try_render("blog", lambda: fetch_json(BLOG_URL), render_blog)
    wakatime_section = try_render("wakatime", lambda: fetch_json(f"{STATUS_URL}?{status_query}"), render_wakatime)
    github_section = try_render("github", fetch_github_footprint, render_github_footprint)

    text = README.read_text(encoding="utf-8")
    if blog_section is not None:
        text = replace_between(text, "<!-- BLOG:START -->", "<!-- BLOG:END -->", blog_section)
    if wakatime_section is not None:
        text = replace_between(text, "<!-- WAKATIME:START -->", "<!-- WAKATIME:END -->", wakatime_section)
    if github_section is not None:
        text = replace_between(text, "<!-- GITHUB:START -->", "<!-- GITHUB:END -->", github_section)
    README.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

