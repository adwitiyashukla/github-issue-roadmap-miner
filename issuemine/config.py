import os
from types import SimpleNamespace

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

STATES = ("all", "open", "closed")
ANALYZERS = ("word", "char_wb", "char")

SPEC = {
    "source": {
        "owner": ("str", {}),
        "repo": ("str", {}),
        "state": ("str", {"choices": STATES}),
    },
    "ingest": {
        "per_page": ("int", {"low": 1, "high": 100}),
        "max_pages": ("int", {"low": 0}),
        "request_timeout": ("int", {"low": 1, "high": 600}),
        "retry_attempts": ("int", {"low": 0, "high": 20}),
        "retry_backoff": ("float", {"low": 1.0, "high": 10.0}),
        "page_sleep": ("float", {"low": 0.0, "high": 60.0}),
        "keep_pull_requests": ("bool", {}),
        "body_max_chars": ("int", {"low": 1, "high": 1000000}),
        "max_items_per_window": ("int", {"low": 100, "high": 1000000}),
    },
    "prepare": {
        "min_chars": ("int", {"low": 0, "high": 100000}),
        "max_chars": ("int", {"low": 1, "high": 1000000}),
        "drop_authors": ("strlist", {}),
        "drop_label_prefixes": ("strlist", {}),
        "near_duplicate_threshold": ("float", {"low": 0.0, "high": 1.0}),
        "max_near_duplicate_share": ("float", {"low": 0.0, "high": 1.0}),
        "dedup_head_chars": ("int", {"low": 50, "high": 100000}),
        "dedup_analyzer": ("str", {"choices": ANALYZERS}),
        "dedup_ngram_min": ("int", {"low": 1, "high": 10}),
        "dedup_ngram_max": ("int", {"low": 1, "high": 10}),
        "dedup_max_features": ("int", {"low": 1000, "high": 5000000}),
        "title_weight": ("int", {"low": 1, "high": 20}),
        "template_sections": ("strlist", {}),
        "log_line_markers": ("strlist", {}),
    },
    "embed": {
        "max_features": ("int", {"low": 100, "high": 2000000}),
        "min_df": ("int", {"low": 1, "high": 1000}),
        "max_df": ("float", {"low": 0.01, "high": 1.0}),
        "ngram_max": ("int", {"low": 1, "high": 4}),
        "svd_components": ("int", {"low": 2, "high": 2000}),
        "random_state": ("int", {"low": 0}),
    },
    "cluster": {
        "n_clusters": ("int", {"low": 2, "high": 500}),
        "n_init": ("int", {"low": 1, "high": 100}),
        "random_state": ("int", {"low": 0}),
        "top_terms": ("int", {"low": 1, "high": 50}),
    },
    "score": {
        "weight_volume": ("float", {"low": 0.0, "high": 1.0}),
        "weight_breadth": ("float", {"low": 0.0, "high": 1.0}),
        "weight_unresolved": ("float", {"low": 0.0, "high": 1.0}),
        "weight_engagement": ("float", {"low": 0.0, "high": 1.0}),
        "weight_recency": ("float", {"low": 0.0, "high": 1.0}),
        "recent_days": ("int", {"low": 1, "high": 3650}),
        "min_theme_size": ("int", {"low": 1, "high": 100000}),
        "min_cohesion_z": ("float", {"low": -10.0, "high": 0.0}),
    },
    "report": {
        "roadmap_themes": ("int", {"low": 1, "high": 200}),
        "evidence_per_theme": ("int", {"low": 1, "high": 50}),
    },
    "paths": {
        "data_dir": ("path", {}),
        "issues_file": ("path", {}),
        "state_file": ("path", {}),
        "prepared_file": ("path", {}),
        "vectors_file": ("path", {}),
        "terms_file": ("path", {}),
        "clusters_file": ("path", {}),
        "themes_file": ("path", {}),
        "quality_file": ("path", {}),
        "roadmap_file": ("path", {}),
        "dashboard_file": ("path", {}),
    },
}

WEIGHT_KEYS = (
    "weight_volume",
    "weight_breadth",
    "weight_unresolved",
    "weight_engagement",
    "weight_recency",
)


class ConfigError(ValueError):
    pass


def _text(value, label, rules):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must be a non empty string" % label)
    value = value.strip()
    choices = rules.get("choices")
    if choices and value not in choices:
        raise ConfigError("%s must be one of %s" % (label, ", ".join(choices)))
    return value


def _whole(value, label, rules):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("%s must be an integer" % label)
    return _bounded(value, label, rules)


def _decimal(value, label, rules):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("%s must be a number" % label)
    return _bounded(float(value), label, rules)


def _bounded(value, label, rules):
    low = rules.get("low")
    high = rules.get("high")
    if low is not None and value < low:
        raise ConfigError("%s must be at least %s" % (label, low))
    if high is not None and value > high:
        raise ConfigError("%s must be at most %s" % (label, high))
    return value


def _flag(value, label, rules):
    if not isinstance(value, bool):
        raise ConfigError("%s must be true or false" % label)
    return value


def _textlist(value, label, rules):
    if not isinstance(value, list):
        raise ConfigError("%s must be a list of strings" % label)
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("%s[%d] must be a non empty string" % (label, index))
        out.append(item.strip())
    return out


def _relative(value, label, rules):
    value = _text(value, label, rules)
    if os.path.isabs(value) or value.startswith("~"):
        raise ConfigError("%s must be a relative path" % label)
    parts = os.path.normpath(value).replace("\\", "/").split("/")
    if ".." in parts:
        raise ConfigError("%s must not climb above the project folder" % label)
    return value


READERS = {
    "str": _text,
    "int": _whole,
    "float": _decimal,
    "bool": _flag,
    "strlist": _textlist,
    "path": _relative,
}


def _check_section(raw, name):
    if name not in raw:
        raise ConfigError("config is missing the [%s] section" % name)
    section = raw[name]
    if not isinstance(section, dict):
        raise ConfigError("[%s] must be a table" % name)
    expected = set(SPEC[name])
    unknown = sorted(set(section) - expected)
    if unknown:
        raise ConfigError("[%s] has unknown keys: %s" % (name, ", ".join(unknown)))
    missing = sorted(expected - set(section))
    if missing:
        raise ConfigError("[%s] is missing keys: %s" % (name, ", ".join(missing)))
    return section


def _check_cross(values):
    prepare = values["prepare"]
    if prepare["min_chars"] >= prepare["max_chars"]:
        raise ConfigError("prepare.min_chars must be smaller than prepare.max_chars")
    if prepare["dedup_ngram_min"] > prepare["dedup_ngram_max"]:
        raise ConfigError("prepare.dedup_ngram_min must not exceed prepare.dedup_ngram_max")

    score = values["score"]
    total = sum(score[key] for key in WEIGHT_KEYS)
    if total <= 0:
        raise ConfigError("at least one [score] weight must be above zero")
    if abs(total - 1.0) > 0.001:
        raise ConfigError("[score] weights must add up to 1.0, they add up to %.3f" % total)

    paths = values["paths"]
    root = os.path.normpath(paths["data_dir"]).replace("\\", "/")
    for key, value in paths.items():
        if key == "data_dir":
            continue
        normalized = os.path.normpath(value).replace("\\", "/")
        if not normalized.startswith(root + "/"):
            raise ConfigError("paths.%s must sit inside paths.data_dir" % key)


def parse_config(raw, base_dir):
    unknown = sorted(set(raw) - set(SPEC))
    if unknown:
        raise ConfigError("config has unknown sections: %s" % ", ".join(unknown))

    values = {}
    for name, fields in SPEC.items():
        section = _check_section(raw, name)
        parsed = {}
        for key, (kind, rules) in fields.items():
            parsed[key] = READERS[kind](section[key], "%s.%s" % (name, key), rules)
        values[name] = parsed

    _check_cross(values)

    values["paths"] = {
        key: os.path.join(base_dir, value) for key, value in values["paths"].items()
    }
    sections = {name: SimpleNamespace(**fields) for name, fields in values.items()}
    return SimpleNamespace(base_dir=base_dir, **sections)


def load_config(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ConfigError("config file not found: %s" % path)
    with open(path, "rb") as handle:
        try:
            raw = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise ConfigError("config is not valid toml: %s" % error)
    return parse_config(raw, os.path.dirname(path))
