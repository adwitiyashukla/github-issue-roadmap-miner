import re

FENCED = re.compile(r"```.*?```", re.DOTALL)
INDENTED = re.compile(r"(?m)^(?: {4}|\t).*$")
INLINE_CODE = re.compile(r"`[^`]*`")
HTML_TAG = re.compile(r"<[^>]+>")
URL = re.compile(r"https?://\S+|www\.\S+")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*.*$")
QUOTE = re.compile(r"(?m)^\s{0,3}>.*$")
PLACEHOLDER = re.compile(r"_no response_", re.IGNORECASE)
HEXISH = re.compile(r"\b(?:0x)?[0-9a-f]{6,}\b")
PATHISH = re.compile(r"[a-z]:\\[^\s]+|/(?:home|usr|var|opt|etc|mnt|users)/\S+")
NUMBER = re.compile(r"\b\d+(?:\.\d+)*\b")
NONWORD = re.compile(r"[^a-z0-9_\s]+")
SPACES = re.compile(r"\s+")


def section_pattern(names):
    if not names:
        return None
    joined = "|".join(re.escape(name) for name in names)
    return re.compile(
        r"(?ims)^\s{0,3}#{1,6}\s*(?:%s)\s*$.*?(?=^\s{0,3}#{1,6}\s|\Z)" % joined
    )


def drop_log_lines(text, markers):
    if not markers:
        return text
    kept = []
    for line in text.splitlines():
        low = line.lower()
        if any(marker in low for marker in markers):
            continue
        kept.append(line)
    return "\n".join(kept)


def normalize(title, body, title_weight, sections=None, markers=()):
    text = body or ""
    if sections is not None:
        text = sections.sub(" ", text)
    text = FENCED.sub(" ", text)
    text = drop_log_lines(text, markers)
    text = PLACEHOLDER.sub(" ", text)
    text = IMAGE.sub(" ", text)
    text = LINK.sub(r"\1", text)
    text = HEADING.sub(" ", text)
    text = QUOTE.sub(" ", text)
    text = INDENTED.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = HTML_TAG.sub(" ", text)
    text = URL.sub(" ", text)
    text = text.lower()
    text = PATHISH.sub(" ", text)
    text = HEXISH.sub(" ", text)
    text = NUMBER.sub(" ", text)
    text = NONWORD.sub(" ", text)

    head = (title or "").lower()
    head = URL.sub(" ", head)
    head = NUMBER.sub(" ", head)
    head = NONWORD.sub(" ", head)

    merged = ((head + " ") * max(1, title_weight)) + text
    return SPACES.sub(" ", merged).strip()
