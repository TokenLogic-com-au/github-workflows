"""Sanitizes untrusted model markdown before it is posted as a GitHub comment: strips HTML/images, neutralizes mentions, #refs and alert syntax, de-links non-allowlisted hosts, truncates. The caller adds the dedup marker AFTER sanitizing; the marker is never sanitized itself."""
import re
from urllib.parse import urlparse

ALLOWED_LINK_HOSTS = {
    "github.com",
    "governance.aave.com",
    "snapshot.org",
    "app.aave.com",
    "etherscan.io",
    "arbiscan.io",
    "basescan.org",
    "snowtrace.io",
    "polygonscan.com",
    "gnosisscan.io",
    "bscscan.com",
    "lineascan.build",
    "optimistic.etherscan.io",
    "sonicscan.org",
    "zkevm.polygonscan.com",
}

_HTML_TAG_RE = re.compile(r"<!--.*?-->|<[^>]+>", re.DOTALL)
_ALERT_SYNTAX_RE = re.compile(r"\[!(\w+)\]")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MENTION_RE = re.compile(r"@(?=\w)")
_ISSUE_REF_RE = re.compile(r"#(?=\d)")
_REF_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s*(https?://\S+).*$", re.MULTILINE)
# One pass over every URL shape so a URL consumed by a link is not re-matched as bare.
_LINK_RE = re.compile(
    r"(?P<inline>\[(?P<itext>[^\]]*)\]\((?P<iurl>https?://[^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<refdef>^\[(?P<drefname>[^\]]+)\]:\s*(?P<durl>https?://\S+).*$)"
    r"|(?P<refuse>\[(?P<utext>[^\]]*)\]\[(?P<urefname>[^\]]+)\])"
    r"|(?P<bare>https?://\S+)",
    re.MULTILINE,
)

ZERO_WIDTH_SPACE = "​"


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def _drop_images(text: str) -> str:
    return _IMAGE_RE.sub("", text)


def _neutralize_mentions(text: str) -> str:
    return _MENTION_RE.sub("@" + ZERO_WIDTH_SPACE, text)


def _neutralize_issue_refs(text: str) -> str:
    return _ISSUE_REF_RE.sub("#" + ZERO_WIDTH_SPACE, text)


def _neutralize_alert_syntax(text: str) -> str:
    # Only our renderer may emit GitHub alert blocks, never raw model text.
    return _ALERT_SYNTAX_RE.sub(lambda m: "[" + ZERO_WIDTH_SPACE + "!" + m.group(1) + "]", text)


def _is_allowed_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_LINK_HOSTS or any(
        host.endswith("." + allowed) for allowed in ALLOWED_LINK_HOSTS
    )


def _delink_disallowed_hosts(text: str) -> str:
    refs = {name.strip().lower(): url for name, url in _REF_DEF_RE.findall(text)}

    def repl(m):
        if m.group("inline"):
            link_text, url = m.group("itext"), m.group("iurl")
            if _is_allowed_host(url):
                return m.group(0)
            return link_text
        if m.group("refdef"):
            return m.group(0) if _is_allowed_host(m.group("durl")) else ""
        if m.group("refuse"):
            link_text = m.group("utext")
            url = refs.get(m.group("urefname").strip().lower())
            if url is not None and _is_allowed_host(url):
                return m.group(0)
            return link_text
        url = m.group("bare")
        return url if _is_allowed_host(url) else ""

    return _LINK_RE.sub(repl, text)


def sanitize_markdown(text: str, max_len: int = 20000) -> str:
    text = _strip_html(text)
    text = _drop_images(text)
    text = _neutralize_mentions(text)
    text = _neutralize_issue_refs(text)
    text = _neutralize_alert_syntax(text)
    text = _delink_disallowed_hosts(text)
    return text[:max_len]


if __name__ == "__main__":
    import sys

    in_path, max_len = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    with open(in_path, encoding="utf-8") as f:
        raw = f.read()
    sys.stdout.write(sanitize_markdown(raw, max_len))
