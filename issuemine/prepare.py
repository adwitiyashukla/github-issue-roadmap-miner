import argparse
import hashlib
import json
import os
import sys
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import ConfigError, load_config
from .textclean import normalize, section_pattern

CHUNK = 400


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def read_rows(path):
    if not os.path.isfile(path):
        raise SystemExit("no ingested issues at %s, run the ingest step first" % path)
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dropped_by_author(row, blocked):
    author = (row.get("author") or "").lower()
    return author in blocked


def dropped_by_label(row, prefixes):
    for label in row.get("labels") or []:
        low = label.lower()
        for prefix in prefixes:
            if low.startswith(prefix):
                return True
    return False


def signature(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def similarity_profile(texts, config):
    matrix = dedup_matrix(texts, config)
    total = matrix.shape[0]
    best = np.zeros(total, dtype=np.float32)
    for start in range(0, total, CHUNK):
        stop = min(start + CHUNK, total)
        block = (matrix[start:stop] @ matrix.T).toarray()
        for offset in range(stop - start):
            block[offset, start + offset] = 0.0
        best[start:stop] = block.max(axis=1)
    return best


def dedup_matrix(texts, config):
    settings = config.prepare
    vectorizer = TfidfVectorizer(
        analyzer=settings.dedup_analyzer,
        ngram_range=(settings.dedup_ngram_min, settings.dedup_ngram_max),
        max_features=settings.dedup_max_features,
        min_df=1,
        max_df=1.0,
        sublinear_tf=True,
    )
    return vectorizer.fit_transform([text[: settings.dedup_head_chars] for text in texts])


def near_duplicates(texts, config):
    threshold = config.prepare.near_duplicate_threshold
    matrix = dedup_matrix(texts, config)
    drop = set()
    total = matrix.shape[0]
    for start in range(0, total, CHUNK):
        stop = min(start + CHUNK, total)
        block = (matrix[start:stop] @ matrix.T).toarray()
        for local in range(stop - start):
            index = start + local
            if index in drop:
                continue
            row = block[local]
            row[: index + 1] = 0.0
            for other in np.nonzero(row >= threshold)[0]:
                drop.add(int(other))
    return drop


def cleaners(config):
    sections = section_pattern([name.lower() for name in config.prepare.template_sections])
    markers = [marker.lower() for marker in config.prepare.log_line_markers]
    return sections, markers


def calibrate(config):
    rows = read_rows(config.paths.issues_file)
    sections, markers = cleaners(config)
    texts = []
    for row in rows:
        text = normalize(
            row.get("title"), row.get("body"), config.prepare.title_weight, sections, markers
        )
        if len(text) >= config.prepare.min_chars:
            texts.append(text[: config.prepare.max_chars])
    log("measuring nearest neighbour similarity across %d issues" % len(texts))
    best = similarity_profile(texts, config)
    log("percentiles of how similar each issue is to its closest match:")
    for percent in (50, 75, 90, 95, 99):
        log("  p%-3d %.3f" % (percent, float(np.percentile(best, percent))))
    log("share of issues flagged at each threshold:")
    for threshold in (0.80, 0.85, 0.90, 0.95, 0.97, 0.99):
        log("  %.2f -> %.1f%%" % (threshold, 100.0 * float((best >= threshold).mean())))
    log("pick a threshold where the flagged share looks like real duplicate volume for this repo.")
    return best


def run(config):
    rows = read_rows(config.paths.issues_file)
    log("loaded %d ingested issues" % len(rows))

    blocked_authors = {name.lower() for name in config.prepare.drop_authors}
    blocked_prefixes = [p.lower() for p in config.prepare.drop_label_prefixes]

    sections, markers = cleaners(config)
    reasons = Counter()
    seen = set()
    kept = []
    for row in rows:
        if dropped_by_author(row, blocked_authors):
            reasons["bot author"] += 1
            continue
        if dropped_by_label(row, blocked_prefixes):
            reasons["blocked label"] += 1
            continue
        text = normalize(
            row.get("title"), row.get("body"), config.prepare.title_weight, sections, markers
        )
        if len(text) < config.prepare.min_chars:
            reasons["too short after cleaning"] += 1
            continue
        text = text[: config.prepare.max_chars]
        key = signature(text)
        if key in seen:
            reasons["exact duplicate"] += 1
            continue
        seen.add(key)
        row["text"] = text
        kept.append(row)

    log("kept %d after filtering, now checking near duplicates" % len(kept))
    drop = near_duplicates([row["text"] for row in kept], config)
    share = len(drop) / len(kept) if kept else 0.0
    if share > config.prepare.max_near_duplicate_share:
        raise SystemExit(
            "near duplicate removal would drop %d of %d issues (%.1f%%), above the %.1f%% limit. "
            "raise prepare.near_duplicate_threshold or prepare.max_near_duplicate_share in config.toml, "
            "or run with --calibrate to see the similarity spread for this repo."
            % (len(drop), len(kept), share * 100, config.prepare.max_near_duplicate_share * 100)
        )
    reasons["near duplicate"] += len(drop)
    kept = [row for index, row in enumerate(kept) if index not in drop]

    os.makedirs(os.path.dirname(config.paths.prepared_file), exist_ok=True)
    with open(config.paths.prepared_file, "w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row) + "\n")

    for reason, count in reasons.most_common():
        log("  dropped %5d  %s" % (count, reason))
    log("prepared %d issues into %s" % (len(kept), config.paths.prepared_file))
    return len(kept), dict(reasons)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.prepare")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        raise SystemExit("config error: %s" % error)
    if args.calibrate:
        calibrate(config)
    else:
        run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
