"""
Web research tools for the Personal AI Assistant.

  web_search(query)   — DuckDuckGo search, no API key required
  read_webpage(url)   — Fetch a URL and extract readable text
"""

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser


# =============================================================================
# HTML → plain text extractor
# =============================================================================

_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0          # skip-tag nesting depth
        self._in_skip = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._depth += 1
            self._in_skip = True

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._depth = max(0, self._depth - 1)
            self._in_skip = self._depth > 0

    def handle_data(self, data):
        if not self._in_skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s{2,}", " ", raw).strip()


# =============================================================================
# Public API
# =============================================================================

def web_search(query: str, max_results: int = 5) -> dict:
    """
    Search the web using DuckDuckGo (no API key needed).
    Returns a list of {title, url, snippet} dicts.
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
        return {"query": query, "results": results}
    except ImportError:
        return {"error": "duckduckgo-search package not installed. Run: pip install duckduckgo-search"}
    except Exception as e:
        return {"error": f"Web search failed: {e}"}


def read_webpage(url: str, max_chars: int = 4000) -> dict:
    """
    Fetch a webpage and return its readable text content.
    Strips scripts, styles, nav, footer, etc.
    Truncates to max_chars (default 4000) to fit model context.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {"error": f"Unsupported content type: {content_type}"}
            html = resp.read().decode("utf-8", errors="ignore")

        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        truncated = len(text) > max_chars
        return {
            "url": url,
            "content": text[:max_chars],
            "truncated": truncated,
            "total_chars": len(text),
        }
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason} — {url}"}
    except urllib.error.URLError as e:
        return {"error": f"Could not reach {url}: {e.reason}"}
    except Exception as e:
        return {"error": f"Failed to read webpage: {e}"}
