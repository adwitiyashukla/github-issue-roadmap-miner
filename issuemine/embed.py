import argparse
import json
import os
import sys

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import Normalizer

from .config import ConfigError, load_config

STOPWORDS = "english"


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def read_prepared(path):
    if not os.path.isfile(path):
        raise SystemExit("no prepared issues at %s, run the prepare step first" % path)
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit("prepared file is empty: %s" % path)
    return rows


def build_matrix(texts, config):
    vectorizer = TfidfVectorizer(
        max_features=config.embed.max_features,
        min_df=config.embed.min_df,
        max_df=config.embed.max_df,
        ngram_range=(1, config.embed.ngram_max),
        stop_words=STOPWORDS,
        sublinear_tf=True,
        strip_accents="ascii",
    )
    matrix = vectorizer.fit_transform(texts)
    return matrix, vectorizer.get_feature_names_out().tolist()


def reduce_matrix(matrix, config):
    components = min(config.embed.svd_components, min(matrix.shape) - 1)
    svd = TruncatedSVD(n_components=components, random_state=config.embed.random_state)
    reduced = svd.fit_transform(matrix)
    reduced = Normalizer(copy=False).fit_transform(reduced)
    return reduced.astype(np.float32), float(svd.explained_variance_ratio_.sum()), components


def run(config):
    rows = read_prepared(config.paths.prepared_file)
    log("embedding %d issues" % len(rows))

    matrix, features = build_matrix([row["text"] for row in rows], config)
    log("tfidf matrix %d x %d with %d nonzero values" % (matrix.shape[0], matrix.shape[1], matrix.nnz))

    reduced, explained, components = reduce_matrix(matrix, config)
    log("reduced to %d components, explained variance %.3f" % (components, explained))

    os.makedirs(os.path.dirname(config.paths.vectors_file), exist_ok=True)
    matrix = matrix.tocsr()
    np.savez_compressed(
        config.paths.vectors_file,
        vectors=reduced,
        numbers=np.array([row["number"] for row in rows], dtype=np.int64),
        tfidf_data=matrix.data.astype(np.float32),
        tfidf_indices=matrix.indices.astype(np.int32),
        tfidf_indptr=matrix.indptr.astype(np.int64),
        tfidf_shape=np.array(matrix.shape, dtype=np.int64),
        explained_variance=np.array([explained], dtype=np.float64),
    )
    with open(config.paths.terms_file, "w", encoding="utf-8") as handle:
        json.dump({"features": features}, handle)

    log("wrote vectors to %s" % config.paths.vectors_file)
    return reduced.shape, explained


def load_vectors(path):
    if not os.path.isfile(path):
        raise SystemExit("no vectors at %s, run the embed step first" % path)
    store = np.load(path)
    matrix = csr_matrix(
        (store["tfidf_data"], store["tfidf_indices"], store["tfidf_indptr"]),
        shape=tuple(store["tfidf_shape"]),
    )
    return store["vectors"], store["numbers"], matrix, float(store["explained_variance"][0])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.embed")
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
