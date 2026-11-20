import argparse
import html
import json
import os
import sys

from .config import ConfigError, load_config

COMPONENT_LABELS = (
    ("volume", "Volume"),
    ("breadth", "Breadth"),
    ("unresolved", "Unresolved"),
    ("engagement", "Engagement"),
    ("recency", "Recency"),
)


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def read_themes(path):
    if not os.path.isfile(path):
        raise SystemExit("no themes at %s, run the score step first" % path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_quality(path):
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_roadmap(data, quality, config):
    themes = data["themes"][: config.report.roadmap_themes]
    lines = []
    lines.append("# %s issue roadmap" % data["repo"])
    lines.append("")
    lines.append(
        "Built from %d issues grouped into %d themes. Newest issue in the set is %s."
        % (quality.get("issues", 0), len(data["themes"]), data["generated_from_newest_issue"])
    )
    lines.append("")
    lines.append("Every theme gets one score between 0 and 1. The score is a weighted sum of five")
    lines.append("parts, each rescaled across themes so they are comparable:")
    lines.append("")
    lines.append("| part | weight | what it measures |")
    lines.append("| --- | --- | --- |")
    meaning = {
        "volume": "how many issues landed in the theme",
        "breadth": "how many different people raised it",
        "unresolved": "share of the theme still open",
        "engagement": "average reactions plus comments per issue",
        "recency": "share raised in the last %d days" % data["recent_days"],
    }
    for key, label in COMPONENT_LABELS:
        lines.append("| %s | %.2f | %s |" % (label, data["weights"][key], meaning[key]))
    lines.append("")
    lines.append("Volume, breadth and engagement are log scaled first so one huge theme does not")
    lines.append("flatten everything else.")
    lines.append("")
    if data.get("unfocused"):
        lines.append(
            "Themes whose issues sit far from each other (cohesion more than %.1f standard"
            % abs(data["min_cohesion_z"])
        )
        lines.append("deviations below the average) are left off the ranking, since there is no single")
        lines.append("thing to build for them:")
        lines.append("")
        for item in data["unfocused"]:
            lines.append(
                "- %s, %d issues, cohesion %.3f" % (item["label"], item["size"], item["cohesion"])
            )
        lines.append("")
    lines.append("## Ranking")
    lines.append("")
    lines.append("| rank | theme | score | issues | people | open | recent |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for theme in themes:
        stats = theme["stats"]
        lines.append(
            "| %d | %s | %.3f | %d | %d | %d%% | %d%% |"
            % (
                theme["rank"],
                theme["label"].replace("|", "/"),
                theme["score"],
                stats["size"],
                stats["authors"],
                round(stats["open_rate"] * 100),
                round(stats["recent_rate"] * 100),
            )
        )
    lines.append("")

    for theme in themes:
        stats = theme["stats"]
        lines.append("## %d. %s" % (theme["rank"], theme["label"]))
        lines.append("")
        lines.append("Score %.3f. Keywords: %s" % (theme["score"], ", ".join(theme["keywords"])))
        lines.append("")
        lines.append("Most typical issue: %s" % theme["example"])
        lines.append("")
        lines.append("| metric | value |")
        lines.append("| --- | --- |")
        lines.append("| issues | %d |" % stats["size"])
        lines.append("| distinct people | %d |" % stats["authors"])
        lines.append("| still open | %d of %d (%d%%) |" % (stats["open"], stats["size"], round(stats["open_rate"] * 100)))
        lines.append("| median age of open issues | %d days |" % stats["median_open_age_days"])
        lines.append("| average reactions plus comments | %.2f |" % stats["engagement_mean"])
        lines.append("| raised in last %d days | %d (%d%%) |" % (data["recent_days"], stats["recent"], round(stats["recent_rate"] * 100)))
        lines.append("")
        lines.append("Score breakdown:")
        lines.append("")
        lines.append("| part | scaled | weighted |")
        lines.append("| --- | --- | --- |")
        for key, label in COMPONENT_LABELS:
            lines.append("| %s | %.3f | %.3f |" % (label, theme["components"][key], theme["contributions"][key]))
        lines.append("")
        lines.append("Evidence:")
        lines.append("")
        for item in theme["evidence"]:
            lines.append(
                "- [#%d %s](%s) - %s, %d reactions, %d comments"
                % (item["number"], item["title"], item["url"], item["state"], item["reactions"], item["comments"])
            )
        lines.append("")

    os.makedirs(os.path.dirname(config.paths.roadmap_file), exist_ok=True)
    with open(config.paths.roadmap_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return len(themes)


def bar(value, width=260):
    filled = max(2, int(round(value * width)))
    return (
        '<svg class="bar" width="%d" height="12" role="img" aria-label="score %.3f">'
        '<rect width="%d" height="12" rx="3" class="track"></rect>'
        '<rect width="%d" height="12" rx="3" class="fill"></rect></svg>'
    ) % (width, value, width, filled)


def write_dashboard(data, quality, config):
    themes = data["themes"][: config.report.roadmap_themes]
    esc = html.escape
    parts = []
    parts.append("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    parts.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    parts.append("<title>%s issue themes</title>" % esc(data["repo"]))
    parts.append("<style>")
    parts.append(
        ":root{--ink:#16181d;--muted:#5c6470;--line:#e2e5ea;--bg:#ffffff;--panel:#f7f8fa;--fill:#2f6f4f}"
        "@media(prefers-color-scheme:dark){:root{--ink:#e8eaee;--muted:#9aa3af;--line:#2b2f36;--bg:#14161a;--panel:#1b1e24;--fill:#6cc49a}}"
        "*{box-sizing:border-box}"
        "body{margin:0;padding:32px 16px;background:var(--bg);color:var(--ink);"
        "font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}"
        ".wrap{max-width:1000px;margin:0 auto}"
        "h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}"
        "p.sub{color:var(--muted);margin:0 0 24px}"
        ".cards{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:28px}"
        ".card{flex:1 1 150px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}"
        ".card b{display:block;font-size:22px;font-weight:600}"
        ".card span{color:var(--muted);font-size:13px}"
        ".scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}"
        "table{width:100%;border-collapse:collapse;font-size:14px;min-width:640px}"
        "th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}"
        "th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}"
        "td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}"
        ".bar .track{fill:var(--line)}.bar .fill{fill:var(--fill)}"
        ".kw{color:var(--muted);font-size:12px;display:block;margin-top:2px}"
        "a{color:inherit}"
        "details{margin:6px 0}summary{cursor:pointer;color:var(--muted);font-size:13px}"
        "ul{margin:6px 0 0;padding-left:18px}li{margin:3px 0;font-size:13px}"
    )
    parts.append("</style></head><body><div class=\"wrap\">")
    parts.append("<h1>%s issue themes</h1>" % esc(data["repo"]))
    parts.append(
        "<p class=\"sub\">%d issues grouped into %d themes. Newest issue %s.</p>"
        % (quality.get("issues", 0), len(data["themes"]), esc(data["generated_from_newest_issue"]))
    )

    parts.append("<div class=\"cards\">")
    for value, label in (
        (quality.get("issues", 0), "issues analyzed"),
        (len(data["themes"]), "themes"),
        (quality.get("median_cluster", 0), "median theme size"),
        (quality.get("silhouette", "n/a"), "silhouette"),
        ("%.2f" % quality.get("explained_variance", 0), "variance kept"),
    ):
        parts.append("<div class=\"card\"><b>%s</b><span>%s</span></div>" % (esc(str(value)), esc(label)))
    parts.append("</div>")

    parts.append("<h2>Ranked themes</h2><div class=\"scroll\"><table><thead><tr>")
    for head in ("Rank", "Theme", "Score", "Issues", "People", "Open", "Recent"):
        parts.append("<th%s>%s</th>" % (" class=\"num\"" if head not in ("Rank", "Theme") else "", head))
    parts.append("</tr></thead><tbody>")
    for theme in themes:
        stats = theme["stats"]
        evidence = "".join(
            "<li><a href=\"%s\">#%d %s</a> (%s, %d reactions)</li>"
            % (esc(item["url"] or ""), item["number"], esc(item["title"]), esc(item["state"]), item["reactions"])
            for item in theme["evidence"]
        )
        parts.append("<tr>")
        parts.append("<td class=\"num\">%d</td>" % theme["rank"])
        parts.append(
            "<td>%s<span class=\"kw\">e.g. %s</span>"
            "<details><summary>evidence</summary><ul>%s</ul></details></td>"
            % (esc(theme["label"]), esc(theme["example"]), evidence)
        )
        parts.append("<td class=\"num\">%s %.3f</td>" % (bar(theme["score"], 120), theme["score"]))
        parts.append("<td class=\"num\">%d</td>" % stats["size"])
        parts.append("<td class=\"num\">%d</td>" % stats["authors"])
        parts.append("<td class=\"num\">%d%%</td>" % round(stats["open_rate"] * 100))
        parts.append("<td class=\"num\">%d%%</td>" % round(stats["recent_rate"] * 100))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")

    if data.get("unfocused"):
        parts.append("<h2>Left off the ranking</h2><p class=\"sub\">These themes are too spread out to act on as one item.</p><ul>")
        for item in data["unfocused"]:
            parts.append(
                "<li>%s, %d issues, cohesion %.3f</li>"
                % (esc(item["label"]), item["size"], item["cohesion"])
            )
        parts.append("</ul>")

    parts.append("<h2>How the score is built</h2><div class=\"scroll\"><table><thead><tr><th>Part</th><th class=\"num\">Weight</th><th>Measures</th></tr></thead><tbody>")
    meaning = {
        "volume": "how many issues landed in the theme",
        "breadth": "how many different people raised it",
        "unresolved": "share of the theme still open",
        "engagement": "average reactions plus comments per issue",
        "recency": "share raised in the last %d days" % data["recent_days"],
    }
    for key, label in COMPONENT_LABELS:
        parts.append("<tr><td>%s</td><td class=\"num\">%.2f</td><td>%s</td></tr>" % (label, data["weights"][key], meaning[key]))
    parts.append("</tbody></table></div></div></body></html>")

    os.makedirs(os.path.dirname(config.paths.dashboard_file), exist_ok=True)
    with open(config.paths.dashboard_file, "w", encoding="utf-8") as handle:
        handle.write("".join(parts))


def run(config):
    data = read_themes(config.paths.themes_file)
    quality = read_quality(config.paths.quality_file)
    count = write_roadmap(data, quality, config)
    write_dashboard(data, quality, config)
    log("wrote %d themes to %s" % (count, config.paths.roadmap_file))
    log("wrote dashboard to %s" % config.paths.dashboard_file)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.report")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        raise SystemExit("config error: %s" % error)
    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
