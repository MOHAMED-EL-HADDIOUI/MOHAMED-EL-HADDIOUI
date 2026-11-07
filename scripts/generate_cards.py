#!/usr/bin/env python3
"""Generate self-hosted GitHub stats cards (Tokyo Night) as SVG files.

Runs inside GitHub Actions with the built-in GITHUB_TOKEN, so the profile README
no longer depends on third-party image servers that go down or rate-limit.
Outputs: assets/stats-card.svg, assets/streak-card.svg, assets/languages-card.svg
"""
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from xml.sax.saxutils import escape

USER = os.environ.get("USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = os.environ.get("OUT_DIR", "assets")
EXCLUDE_LANGS = {"Jupyter Notebook"}  # notebooks are huge and hide your real languages

BG, BORDER, TITLE, TEXT, MUTED, ACCENT = "#1a1b27", "#7AA2F7", "#7AA2F7", "#a9b1d6", "#565f89", "#bb9af7"
FALLBACK_COLORS = ["#7AA2F7", "#bb9af7", "#9ece6a", "#e0af68", "#f7768e", "#7dcfff", "#ff9e64"]

QUERY = """
query($login:String!){
  user(login:$login){
    name
    followers{totalCount}
    pullRequests{totalCount}
    issues{totalCount}
    repositories(ownerAffiliations:OWNER, isFork:false, privacy:PUBLIC, first:100){
      totalCount
      nodes{
        stargazerCount
        languages(first:10, orderBy:{field:SIZE, direction:DESC}){
          edges{size node{name color}}
        }
      }
    }
    contributionsCollection{
      totalCommitContributions
      contributionCalendar{
        totalContributions
        weeks{contributionDays{date contributionCount}}
      }
    }
  }
}
"""


def fetch(login):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if "errors" in payload or not payload.get("data", {}).get("user"):
        raise RuntimeError(json.dumps(payload.get("errors", payload))[:500])
    return payload["data"]["user"]


def streaks(days):
    counts = {d["date"]: d["contributionCount"] for d in days}
    ordered = sorted(counts)
    longest = run = 0
    for d in ordered:
        run = run + 1 if counts[d] > 0 else 0
        longest = max(longest, run)
    # current streak: walk back from today (today may still be empty)
    cur, day = 0, date.today()
    if counts.get(day.isoformat(), 0) == 0:
        day -= timedelta(days=1)
    while counts.get(day.isoformat(), 0) > 0:
        cur += 1
        day -= timedelta(days=1)
    return cur, longest


def frame(w, h, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
<style>
  .t{{font:600 18px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TITLE}}}
  .l{{font:400 14px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TEXT}}}
  .v{{font:700 14px 'Segoe UI',Ubuntu,Sans-Serif;fill:{ACCENT}}}
  .big{{font:700 28px 'Segoe UI',Ubuntu,Sans-Serif;fill:{ACCENT}}}
  .s{{font:400 12px 'Segoe UI',Ubuntu,Sans-Serif;fill:{MUTED}}}
  .fade{{opacity:0;animation:f .6s ease-out forwards}}
  @keyframes f{{to{{opacity:1}}}}
  @keyframes g{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
  .bar{{transform-box:fill-box;transform-origin:left;animation:g .9s ease-out forwards}}
</style>
<rect x=".5" y=".5" rx="12" width="{w-1}" height="{h-1}" fill="{BG}" stroke="{BORDER}" stroke-opacity=".35"/>
<text x="24" y="34" class="t">{escape(title)}</text>
{body}
</svg>"""


def stats_card(u):
    stars = sum(n["stargazerCount"] for n in u["repositories"]["nodes"])
    rows = [
        ("Total stars earned", stars),
        ("Commits (last 12 months)", u["contributionsCollection"]["totalCommitContributions"]),
        ("Pull requests", u["pullRequests"]["totalCount"]),
        ("Issues opened", u["issues"]["totalCount"]),
        ("Public repositories", u["repositories"]["totalCount"]),
        ("Followers", u["followers"]["totalCount"]),
    ]
    body = ""
    for i, (label, value) in enumerate(rows):
        y = 68 + i * 24
        body += (f'<g class="fade" style="animation-delay:{i*120}ms">'
                 f'<circle cx="30" cy="{y-5}" r="3.5" fill="{ACCENT}"/>'
                 f'<text x="44" y="{y}" class="l">{escape(label)}</text>'
                 f'<text x="330" y="{y}" class="v" text-anchor="end">{value:,}</text></g>')
    name = u.get("name") or USER
    return frame(360, 215, f"{name}'s GitHub Stats", body)


def streak_card(u):
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    cur, longest = streaks(days)
    cols = [(cal["totalContributions"], "Contributions", "last 12 months"),
            (cur, "Current streak", "days"),
            (longest, "Longest streak", "days, last 12 months")]
    body = ""
    for i, (value, label, sub) in enumerate(cols):
        cx = 70 + i * 120
        body += (f'<g class="fade" style="animation-delay:{i*200}ms" text-anchor="middle">'
                 f'<text x="{cx}" y="100" class="big">{value:,}</text>'
                 f'<text x="{cx}" y="126" class="l">{label}</text>'
                 f'<text x="{cx}" y="146" class="s">{sub}</text></g>')
    return frame(360, 175, "Contribution Streak", body)


def languages_card(u):
    totals, colors = {}, {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in EXCLUDE_LANGS:
                continue
            totals[name] = totals.get(name, 0) + e["size"]
            colors[name] = e["node"]["color"] or colors.get(name)
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:6]
    all_bytes = sum(v for _, v in top) or 1
    body, x, bar_w = "", 24, 312
    # stacked bar
    for i, (name, size) in enumerate(top):
        w = max(bar_w * size / all_bytes, 2)
        c = colors.get(name) or FALLBACK_COLORS[i % len(FALLBACK_COLORS)]
        colors[name] = c
        body += f'<rect class="bar" x="{x:.1f}" y="52" width="{w:.1f}" height="10" fill="{c}" style="animation-delay:{i*150}ms"/>'
        x += w
    # legend (2 columns)
    for i, (name, size) in enumerate(top):
        col, row = i % 2, i // 2
        lx, ly = 24 + col * 160, 92 + row * 26
        body += (f'<g class="fade" style="animation-delay:{300+i*100}ms">'
                 f'<circle cx="{lx+5}" cy="{ly-5}" r="5" fill="{colors[name]}"/>'
                 f'<text x="{lx+18}" y="{ly}" class="l">{escape(name)} <tspan class="s">{size/all_bytes*100:.1f}%</tspan></text></g>')
    return frame(360, 175, "Most Used Languages", body)


def main():
    if not USER or not TOKEN:
        sys.exit("USERNAME and GITHUB_TOKEN must be set")
    user = fetch(USER)
    os.makedirs(OUT, exist_ok=True)
    for fname, fn in (("stats-card.svg", stats_card), ("streak-card.svg", streak_card),
                      ("languages-card.svg", languages_card)):
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write(fn(user))
        print("wrote", fname)


if __name__ == "__main__":
    main()
