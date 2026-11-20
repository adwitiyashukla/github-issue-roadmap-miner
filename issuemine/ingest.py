import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import ConfigError, load_config

API_ROOT = "https://api.github.com"
USER_AGENT = "issuemine"
TOKEN_ENV = "GITHUB_TOKEN"


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def token_from_cli():
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=20
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_token():
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        return token
    token = token_from_cli()
    if token:
        log("using the token from the github cli")
        return token
    raise SystemExit(
        "no github credentials. set %s or sign in with: gh auth login" % TOKEN_ENV
    )


def page_url(config, page, since):
    params = {
        "state": config.source.state,
        "per_page": str(config.ingest.per_page),
        "page": str(page),
        "sort": "updated",
        "direction": "asc",
    }
    if since:
        params["since"] = since
    return "%s/repos/%s/%s/issues?%s" % (
        API_ROOT,
        config.source.owner,
        config.source.repo,
        urllib.parse.urlencode(params),
    )


def send(url, token, timeout):
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return dict(response.headers), response.read()


def header_int(headers, name, default=0):
    for key, value in headers.items():
        if key.lower() == name:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
    return default


def cooldown(headers, attempt, backoff):
    retry_after = header_int(headers, "retry-after", 0)
    if retry_after > 0:
        return retry_after
    reset = header_int(headers, "x-ratelimit-reset", 0)
    if reset > 0:
        return max(1, int(reset - time.time()) + 1)
    return int(backoff ** attempt)


def pause_if_exhausted(headers):
    remaining = header_int(headers, "x-ratelimit-remaining", -1)
    if remaining != 0:
        return
    wait = cooldown(headers, 1, 2.0)
    log("rate limit reached, sleeping %d seconds" % wait)
    time.sleep(wait)


def get_page(url, token, config):
    attempt = 0
    while True:
        attempt += 1
        try:
            headers, body = send(url, token, config.ingest.request_timeout)
            pause_if_exhausted(headers)
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as error:
            headers = dict(error.headers or {})
            if error.code == 401:
                raise SystemExit("github rejected the token, check %s" % TOKEN_ENV)
            if error.code == 422:
                return None
            if error.code in (403, 429) and attempt <= config.ingest.retry_attempts:
                wait = cooldown(headers, attempt, config.ingest.retry_backoff)
                log("throttled, waiting %d seconds" % wait)
                time.sleep(wait)
                continue
            if error.code >= 500 and attempt <= config.ingest.retry_attempts:
                time.sleep(config.ingest.retry_backoff ** attempt)
                continue
            raise SystemExit("github returned %d for %s" % (error.code, url))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt <= config.ingest.retry_attempts:
                time.sleep(config.ingest.retry_backoff ** attempt)
                continue
            raise SystemExit("request failed: %s" % error)


def trim(item, body_max_chars):
    reactions = item.get("reactions") or {}
    labels = []
    for label in item.get("labels") or []:
        if isinstance(label, dict) and label.get("name"):
            labels.append(label["name"])
        elif isinstance(label, str):
            labels.append(label)
    return {
        "number": item.get("number"),
        "title": (item.get("title") or "").strip(),
        "body": (item.get("body") or "")[:body_max_chars],
        "state": item.get("state"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "labels": labels,
        "comments": item.get("comments") or 0,
        "reactions_total": reactions.get("total_count") or 0,
        "reactions_plus_one": reactions.get("+1") or 0,
        "author": (item.get("user") or {}).get("login"),
        "author_association": item.get("author_association"),
        "url": item.get("html_url"),
    }


def load_seen(path):
    seen = set()
    if not os.path.isfile(path):
        return seen
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                number = json.loads(line).get("number")
            except json.JSONDecodeError:
                continue
            if number is not None:
                seen.add(number)
    return seen


def load_state(path):
    if not os.path.isfile(path):
        return {"since": "", "written": 0}
    with open(path, "r", encoding="utf-8") as handle:
        try:
            state = json.load(handle)
        except json.JSONDecodeError:
            return {"since": "", "written": 0}
    if not isinstance(state, dict) or not isinstance(state.get("since"), str):
        return {"since": "", "written": 0}
    return state


def save_state(path, since, written):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"since": since, "written": written}, handle)
    os.replace(tmp, path)


def run(config, resume):
    token = read_token()
    os.makedirs(os.path.dirname(config.paths.issues_file), exist_ok=True)

    page_cap = max(1, config.ingest.max_items_per_window // config.ingest.per_page)

    if resume:
        seen = load_seen(config.paths.issues_file)
        since = load_state(config.paths.state_file)["since"]
        mode = "a"
        log("resuming from %s with %d issues already stored" % (since or "the start", len(seen)))
    else:
        seen = set()
        since = ""
        mode = "w"

    written = len(seen)
    skipped = 0
    windows = 0
    finished = False

    with open(config.paths.issues_file, mode, encoding="utf-8") as handle:
        while not finished:
            windows += 1
            page = 1
            window_new = 0
            newest = since
            while page <= page_cap:
                if config.ingest.max_pages and windows == 1 and page > config.ingest.max_pages:
                    finished = True
                    log("stopping at max_pages")
                    break
                items = get_page(page_url(config, page, since), token, config)
                if items is None:
                    log("page %d refused by github, starting a new window" % page)
                    break
                if not items:
                    finished = True
                    break
                batch = 0
                for item in items:
                    stamp = item.get("updated_at")
                    if stamp and stamp > newest:
                        newest = stamp
                    if not config.ingest.keep_pull_requests and "pull_request" in item:
                        skipped += 1
                        continue
                    number = item.get("number")
                    if number is None or number in seen:
                        continue
                    seen.add(number)
                    handle.write(json.dumps(trim(item, config.ingest.body_max_chars)) + "\n")
                    batch += 1
                window_new += batch
                written += batch
                handle.flush()
                save_state(config.paths.state_file, since, written)
                log(
                    "window %d page %d: kept %d, total %d issues, %d prs skipped"
                    % (windows, page, batch, written, skipped)
                )
                if len(items) < config.ingest.per_page:
                    finished = True
                    break
                page += 1
                if config.ingest.page_sleep:
                    time.sleep(config.ingest.page_sleep)

            if finished:
                break
            if not newest or newest == since:
                log("no newer timestamp to advance to, stopping")
                break
            if window_new == 0:
                log("window added nothing new, stopping")
                break
            since = newest
            save_state(config.paths.state_file, since, written)
            log("advancing to issues updated at or after %s" % since)

    log("done, %d issues written to %s" % (written, config.paths.issues_file))
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(prog="issuemine.ingest")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        raise SystemExit("config error: %s" % error)
    run(config, args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
