# github-issue-roadmap-miner

Big open source projects get thousands of issues. Reading all of them to decide what to fix next is not realistic, so I built a pipeline that does the first pass. It pulls every issue from a GitHub repo, groups them into themes, scores each theme, and writes out a ranked list with links back to the real issues behind every line.

I ran it on ollama/ollama. Everything below comes from that run.

## What it does

The pipeline has six steps and each one writes its output to `data/` so you can rerun any step on its own.

1. ingest pulls every issue through the GitHub API and skips pull requests
2. prepare cleans the text and drops bot issues, short issues and duplicates
3. embed turns each issue into a vector with TF-IDF and SVD
4. cluster groups the vectors into themes with KMeans
5. score ranks the themes
6. report writes `roadmap.md` and a `dashboard.html` you can open in a browser

## Results on ollama/ollama

Issues pulled on November 20, 2026.

| step | number |
| --- | --- |
| issues pulled | 11,637 |
| pull requests skipped | 7,687 |
| too short after cleaning | 131 |
| near duplicates removed | 81 |
| exact duplicates removed | 26 |
| issues analyzed | 11,399 |
| themes ranked | 24 |
| themes set aside as unfocused | 1 |

Top 10 themes:

| rank | theme | issues | people | still open | last 180 days | score |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | users / feature / ai | 751 | 651 | 36% | 13% | 0.730 |
| 2 | mlx / request / runner | 476 | 422 | 51% | 69% | 0.680 |
| 3 | failed / server error / internal server | 778 | 699 | 15% | 7% | 0.627 |
| 4 | ollama support / does support / add support | 444 | 369 | 27% | 5% | 0.590 |
| 5 | download / models / downloaded | 551 | 480 | 20% | 6% | 0.557 |
| 6 | vram / ram / load | 510 | 445 | 25% | 11% | 0.547 |
| 7 | tools / tool calling / tool calls | 349 | 317 | 43% | 28% | 0.528 |
| 8 | use gpu / intel / cpu gpu | 514 | 490 | 15% | 3% | 0.520 |
| 9 | windows / ollama app / macos | 395 | 338 | 35% | 16% | 0.492 |
| 10 | endpoint / ollama api / api generate | 468 | 423 | 21% | 6% | 0.484 |

The part I find most useful is how the columns disagree with each other. Server errors are the biggest theme by issue count, but only 15% of them are still open, so the team is already on top of it. The MLX runner theme is smaller, yet half of it is unresolved and 69% of it showed up in the last 180 days. That is the newest pain point in the repo and it ranks second for that reason. Tool calling is in a similar spot with 43% still open.

## How the score works

Each theme gets five numbers. Each one is rescaled across themes to sit between 0 and 1, then they are added up with these weights.

| part | weight | what it measures |
| --- | --- | --- |
| volume | 0.30 | how many issues are in the theme |
| breadth | 0.25 | how many different people opened them |
| unresolved | 0.20 | share of the theme still open |
| engagement | 0.15 | average reactions plus comments per issue |
| recency | 0.10 | share opened in the last 180 days |

Volume, breadth and engagement are log scaled first so one huge theme cannot flatten the rest. All of the weights live in `config.toml` and the config check refuses to run if they do not add up to 1.

## Decisions I had to make

GitHub's REST API stops paging after 10,000 items. Page 100 returns HTTP 422, so a straight page loop silently stops early. Ingest walks forward in windows sorted by `updated_at` instead, starting each new window at the newest timestamp it has seen and skipping repeats by issue number. It also saves its place after every page, so `--resume` picks up where a crashed run stopped.

Most Ollama issues come from a bug template. The template adds `_No response_` placeholders, OS and GPU checkbox answers, and pasted server logs. Left alone, these formed their own clusters, like one with 920 issues that only had the placeholder in common. Prepare now drops the template sections and log lines listed in `config.toml` before anything else runs.

I did not want to guess the near duplicate threshold, so `prepare --calibrate` measures how close each issue is to its nearest neighbor. On Ollama the median is 0.342, and a threshold of 0.85 flags 1.7% of issues. There is also a guard that stops the run if duplicate removal would ever drop more than 15% of the data.

I started with HDBSCAN for clustering. On the real issues it found 2 clusters and left 91.9% of the issues as noise. A ranking that ignores most of the issues is not useful, so I switched to KMeans, which puts every issue in a theme. I picked 25 themes by reading the keywords at different sizes. At 25 it already splits "add support" requests into two groups, so going higher only cuts topics into pieces.

KMeans always makes one leftover bucket for issues that fit nowhere. Here it held 1,918 issues and its keywords were generic. Because it is the biggest group it would have ranked first, which would be wrong. So I measure how tight each theme is, as the average similarity of its issues to the theme center. The leftover bucket scored 2.96 standard deviations below the average, while the next lowest theme was 1.54 below. Anything more than 2 below gets reported separately instead of ranked.

Theme names come from the words that show up much more inside a theme than across all issues, so filler words like "using" and "like" do not end up in the names. Each theme also shows its most typical issue as an example.

Running the pipeline twice gives byte identical output. My Windows laptop and a Linux machine also produced the same results, apart from line endings.

## Run it

I ran it on Python 3.11 and 3.13.

```
pip install -r requirements.txt
python -m issuemine
```

That runs every step. To start from a later step, or to run only one:

```
python -m issuemine --from cluster
python -m issuemine --only report
python -m issuemine.prepare --calibrate
```

For the GitHub API it uses the `GITHUB_TOKEN` environment variable. If that is not set, it asks the GitHub CLI for the token of your logged in account. A token with no scopes is enough for public repos.

Everything after ingest took 47.8 seconds on my 8 GB laptop.

To point it at another repo, change `owner` and `repo` in `config.toml`. The template sections and log markers are specific to Ollama's issue template, so check those too.

## Files

| file | what it does |
| --- | --- |
| `config.toml` | every setting, checked on load |
| `issuemine/config.py` | loads and validates the config |
| `issuemine/ingest.py` | pulls issues from GitHub |
| `issuemine/textclean.py` | strips templates, logs, code and markdown |
| `issuemine/prepare.py` | filtering, duplicates and calibration |
| `issuemine/embed.py` | TF-IDF and SVD |
| `issuemine/cluster.py` | KMeans, keywords and cohesion |
| `issuemine/score.py` | the ranking |
| `issuemine/report.py` | roadmap and dashboard |
