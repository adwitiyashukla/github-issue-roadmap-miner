import argparse
import sys
import time

from . import cluster, embed, ingest, prepare, report, score
from .config import ConfigError, load_config

STAGES = (
    ("ingest", ingest),
    ("prepare", prepare),
    ("embed", embed),
    ("cluster", cluster),
    ("score", score),
    ("report", report),
)
NAMES = [name for name, _ in STAGES]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--from", dest="start", choices=NAMES, default="ingest")
    parser.add_argument("--only", choices=NAMES)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as error:
        raise SystemExit("config error: %s" % error)

    if args.only:
        selected = [(name, mod) for name, mod in STAGES if name == args.only]
    else:
        selected = STAGES[NAMES.index(args.start):]

    total = time.time()
    for name, module in selected:
        sys.stdout.write("\n== %s ==\n" % name)
        sys.stdout.flush()
        started = time.time()
        if name == "ingest":
            module.run(config, args.resume)
        else:
            module.run(config)
        sys.stdout.write("%s finished in %.1fs\n" % (name, time.time() - started))
    sys.stdout.write("\npipeline finished in %.1fs\n" % (time.time() - total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
