import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

from .config import ConfigError, load_config

STAMP = "%Y-%m-%dT%H:%M:%SZ"
COMPONENTS = ("volume", "breadth", "unresolved", "engagement", "recency")


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, STAMP).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_jsonl(path, label):
    if not os.path.isfile(path):
        raise SystemExit("missing %s at %s" % (label, path))
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_clusters(path):
    if not os.path.isfile(path):
        raise SystemExit("no clusters at %s, run the cluster step first" % path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["clusters"]


def newest_timestamp(issues):
    stamps = [parse_time(row.get("created_at")) for row in issues]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else datetime.now(timezone.utc)


def measure(issues, now, recent_days):
    open_rows = [r for r in issues if r.get("state") == "open"]
    authors = {r.get("author") for r in issues if r.get("author")}
    engagement = [
        (r.get("reactions_total") or 0) + (r.get("comments") or 0) for r in issues
    ]
    recent = 0
    ages = []
    for row in issues:
        created = parse_time(row.get("created_at"))
        if created is None:
            continue
        age = (now - created).days
        if age <= recent_days:
            recent += 1
        if row.get("state") == "open":
            ages.append(age)
    ages.sort()
    median_open_age = ages[len(ages) // 2] if ages else 0
    return {
        "size": len(issues),
        "authors": len(authors),
        "open": len(open_rows),
        "closed": len(issues) - len(open_rows),
        "open_rate": round(len(open_rows) / len(issues), 4) if issues else 0.0,
        "engagement_mean": round(sum(engagement) / len(issues), 2) if issues else 0.0,
        "recent": recent,
        "recent_rate": round(recent / len(issues), 4) if issues else 0.0,
        "median_open_age_days": median_open_age,
    }


def short_label(terms, limit=3):
    chosen = []
    for term in terms:
        parts = set(term.split())
        if any(parts <= set(other.split()) for other in chosen):
            continue
        chosen = [other for other in chosen if not set(other.split()) <= parts]
        chosen.append(term)
    return " / ".join(chosen[:limit])


def split_unfocused(clusters, min_z):
    values = [item.get("cohesion", 0.0) for item in clusters]
    if len(values) < 3:
        return clusters, []
    mean = sum(values) / len(values)
    spread = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if spread == 0.0:
        return clusters, []
    focused = []
    unfocused = []
    for item in clusters:
        item["cohesion_z"] = round((item.get("cohesion", 0.0) - mean) / spread, 3)
        if item["cohesion_z"] < min_z:
            unfocused.append(item)
        else:
            focused.append(item)
    return focused, unfocused


def scale(values):
    low = min(values)
    high = max(values)
    if high - low < 1e-12:
        return [1.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def build(config):
    clusters, unfocused = split_unfocused(
        read_clusters(config.paths.clusters_file), config.score.min_cohesion_z
    )
    issues = read_jsonl(config.paths.prepared_file, "prepared issues")
    by_number = {row["number"]: row for row in issues}
    now = newest_timestamp(issues)

    themes = []
    for item in clusters:
        rows = [by_number[n] for n in item["numbers"] if n in by_number]
        if len(rows) < config.score.min_theme_size:
            continue
        stats = measure(rows, now, config.score.recent_days)
        head = by_number.get(item.get("medoid"))
        themes.append(
            {
                "cluster": item["cluster"],
                "label": short_label(item["terms"]),
                "example": (head or rows[0]).get("title", "").strip(),
                "cohesion": item.get("cohesion"),
                "keywords": item["terms"],
                "stats": stats,
                "issues": sorted(
                    rows,
                    key=lambda r: (r.get("reactions_total") or 0) + (r.get("comments") or 0),
                    reverse=True,
                ),
            }
        )

    if not themes:
        raise SystemExit("no theme reached score.min_theme_size, lower it in config.toml")

    raw = {
        "volume": [math.log1p(t["stats"]["size"]) for t in themes],
        "breadth": [math.log1p(t["stats"]["authors"]) for t in themes],
        "unresolved": [t["stats"]["open_rate"] for t in themes],
        "engagement": [math.log1p(t["stats"]["engagement_mean"]) for t in themes],
        "recency": [t["stats"]["recent_rate"] for t in themes],
    }
    scaled = {name: scale(values) for name, values in raw.items()}
    weights = {name: getattr(config.score, "weight_" + name) for name in COMPONENTS}

    for index, theme in enumerate(themes):
        parts = {name: round(scaled[name][index], 4) for name in COMPONENTS}
        theme["components"] = parts
        theme["contributions"] = {
            name: round(parts[name] * weights[name], 4) for name in COMPONENTS
        }
        theme["score"] = round(sum(theme["contributions"].values()), 4)

    themes.sort(key=lambda t: t["score"], reverse=True)
    for rank, theme in enumerate(themes, start=1):
        theme["rank"] = rank
    skipped = [
        {
            "label": short_label(item["terms"]),
            "size": item["size"],
            "cohesion": item.get("cohesion"),
            "cohesion_z": item.get("cohesion_z"),
        }
        for item in unfocused
    ]
    return themes, weights, now, skipped


def run(config):
    themes, weights, now, skipped = build(config)
    output = []
    for theme in themes:
        evidence = theme["issues"][: config.report.evidence_per_theme]
        output.append(
            {
                "rank": theme["rank"],
                "cluster": theme["cluster"],
                "label": theme["label"],
                "example": theme["example"],
                "cohesion": theme["cohesion"],
                "keywords": theme["keywords"],
                "score": theme["score"],
                "components": theme["components"],
                "contributions": theme["contributions"],
                "stats": theme["stats"],
                "evidence": [
                    {
                        "number": row["number"],
                        "title": row["title"],
                        "state": row["state"],
                        "reactions": row.get("reactions_total") or 0,
                        "comments": row.get("comments") or 0,
                        "url": row.get("url"),
                    }
                    for row in evidence
                ],
            }
        )

    os.makedirs(os.path.dirname(config.paths.themes_file), exist_ok=True)
    with open(config.paths.themes_file, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "repo": "%s/%s" % (config.source.owner, config.source.repo),
                "generated_from_newest_issue": now.strftime(STAMP),
                "weights": weights,
                "recent_days": config.score.recent_days,
                "min_cohesion_z": config.score.min_cohesion_z,
                "themes": output,
                "unfocused": skipped,
            },
            handle,
            indent=2,
        )

    log("scored %d themes, set aside %d unfocused" % (len(output), len(skipped)))
    for item in skipped:
        log("  unfocused: %s (%d issues, cohesion z %.2f)" % (item["label"], item["size"], item["cohesion_z"]))
    for theme in output[:10]:
        log(
            "  %.3f  %5d issues  %4d authors  %3d%% open  %s"
            % (
                theme["score"],
                theme["stats"]["size"],
                theme["stats"]["authors"],
                round(theme["stats"]["open_rate"] * 100),
                theme["label"][:52],
            )
        )
    log("wrote %s" % config.paths.themes_file)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.score")
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
