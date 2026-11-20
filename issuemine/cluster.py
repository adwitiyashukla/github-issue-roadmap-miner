import argparse
import json
import os
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from .config import ConfigError, load_config
from .embed import load_vectors


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def fit(vectors, config):
    model = KMeans(
        n_clusters=config.cluster.n_clusters,
        n_init=config.cluster.n_init,
        random_state=config.cluster.random_state,
    )
    return model.fit_predict(vectors)


def medoid(vectors, rows):
    block = vectors[rows]
    centre = block.mean(axis=0)
    distances = np.linalg.norm(block - centre, axis=1)
    return rows[int(np.argmin(distances))]


def cohesion(vectors, rows):
    block = vectors[rows]
    centre = block.mean(axis=0)
    length = float(np.linalg.norm(centre))
    if length == 0.0:
        return 0.0
    return float((block @ (centre / length)).mean())


def top_terms(matrix, features, rows, count, baseline):
    if not rows:
        return []
    lift = np.asarray(matrix[rows].mean(axis=0)).ravel() - baseline
    order = np.argsort(lift)[::-1][:count]
    return [features[i] for i in order if lift[i] > 0]


def quality(vectors, labels):
    sizes = np.bincount(labels)
    score = None
    if len(sizes) > 1:
        score = float(silhouette_score(vectors, labels, metric="euclidean"))
    return {
        "issues": int(labels.shape[0]),
        "clusters": int(len(sizes)),
        "silhouette": None if score is None else round(score, 4),
        "largest_cluster": int(sizes.max()),
        "smallest_cluster": int(sizes.min()),
        "median_cluster": int(np.median(sizes)),
    }


def run(config):
    vectors, numbers, matrix, explained = load_vectors(config.paths.vectors_file)
    if vectors.shape[0] < config.cluster.n_clusters:
        raise SystemExit("fewer issues than cluster.n_clusters, lower it in config.toml")
    log("clustering %d issues into %d themes" % (vectors.shape[0], config.cluster.n_clusters))

    labels = fit(vectors, config)
    stats = quality(vectors, labels)
    stats["explained_variance"] = round(explained, 4)
    log(
        "silhouette %s, theme sizes from %d to %d"
        % (stats["silhouette"], stats["smallest_cluster"], stats["largest_cluster"])
    )

    with open(config.paths.terms_file, "r", encoding="utf-8") as handle:
        features = json.load(handle)["features"]

    baseline = np.asarray(matrix.mean(axis=0)).ravel()
    grouped = {}
    for index, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(index)

    clusters = []
    for label, rows in sorted(grouped.items()):
        clusters.append(
            {
                "cluster": label,
                "size": len(rows),
                "terms": top_terms(matrix, features, rows, config.cluster.top_terms, baseline),
                "medoid": int(numbers[medoid(vectors, rows)]),
                "cohesion": round(cohesion(vectors, rows), 4),
                "numbers": [int(numbers[i]) for i in rows],
            }
        )
    clusters.sort(key=lambda item: item["size"], reverse=True)

    os.makedirs(os.path.dirname(config.paths.clusters_file), exist_ok=True)
    with open(config.paths.clusters_file, "w", encoding="utf-8") as handle:
        json.dump({"clusters": clusters}, handle)
    with open(config.paths.quality_file, "w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2)

    for item in clusters[:10]:
        log("  %5d issues  %s" % (item["size"], ", ".join(item["terms"][:6])))
    log("wrote %d themes to %s" % (len(clusters), config.paths.clusters_file))
    return clusters, stats


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.cluster")
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
