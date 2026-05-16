import os
import warnings
import urllib.request
from ddgs import DDGS
from langchain_core.tools import tool
from .common import _truncate_output

def _format_results(results: list) -> str:
    """Format a list of search result dicts into a readable string."""
    formatted = []
    for r in results:
        formatted.append(
            f"Title: {r.get('title', 'N/A')}\n"
            f"URL: {r.get('href', r.get('url', 'N/A'))}\n"
            f"Snippet: {r.get('body', r.get('description', 'N/A'))}\n"
        )
    return _truncate_output("\n---\n".join(formatted))


def _search_brave(query: str, max_results: int) -> list:
    """Search using Brave Search API. Requires BRAVE_API_KEY env var."""
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        raise EnvironmentError("BRAVE_API_KEY not set")
    import json
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count={max_results}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    web_results = data.get("web", {}).get("results", [])
    return [
        {"title": r.get("title"), "href": r.get("url"), "body": r.get("description")}
        for r in web_results
    ]


def _search_serpapi(query: str, max_results: int) -> list:
    """Search using SerpAPI. Requires SERPAPI_KEY env var."""
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        raise EnvironmentError("SERPAPI_KEY not set")
    import json
    encoded_query = urllib.parse.quote_plus(query)
    url = (
        f"https://serpapi.com/search.json"
        f"?q={encoded_query}&num={max_results}&api_key={api_key}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    organic = data.get("organic_results", [])
    return [
        {"title": r.get("title"), "href": r.get("link"), "body": r.get("snippet")}
        for r in organic
    ]


import urllib.parse  # needed by Brave / SerpAPI helpers above

@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Perform a live web search to find information, documentation, or code examples.
    Tries DuckDuckGo first; falls back to Brave Search (BRAVE_API_KEY) then SerpAPI
    (SERPAPI_KEY) if DuckDuckGo fails or returns no results.
    Args:
        query: The search term or question to find on the web.
        max_results: The maximum number of search results to return (default 5).
    """
    errors = []

    # --- Engine 1: DuckDuckGo ---
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if results:
            return _format_results(results)
        errors.append("DuckDuckGo: returned no results")
    except Exception as exc:
        errors.append(f"DuckDuckGo: {exc}")

    # --- Engine 2: Brave Search ---
    try:
        results = _search_brave(query, max_results)
        if results:
            return "[via Brave Search]\n" + _format_results(results)
        errors.append("Brave Search: returned no results")
    except EnvironmentError:
        pass  # API key not configured — skip silently
    except Exception as exc:
        errors.append(f"Brave Search: {exc}")

    # --- Engine 3: SerpAPI ---
    try:
        results = _search_serpapi(query, max_results)
        if results:
            return "[via SerpAPI]\n" + _format_results(results)
        errors.append("SerpAPI: returned no results")
    except EnvironmentError:
        pass  # API key not configured — skip silently
    except Exception as exc:
        errors.append(f"SerpAPI: {exc}")

    return "No results found. Errors: " + " | ".join(errors)

@tool
def fetch_url(url: str, text_only: bool = True) -> str:
    """Download and read the content of a specific web URL.
    Use this to read documentation, API references, or source code from websites found during search.
    Args:
        url: The full HTTP/HTTPS URL to fetch.
        text_only: If True (default), return clean readable text stripped of HTML tags,
                   scripts, and styles — like a browser reader mode. Set to False to
                   get the raw HTML.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            raw_html = response.read().decode("utf-8", errors="ignore")

        if not text_only:
            return _truncate_output(raw_html)

        # --- BeautifulSoup reader-mode extraction ---
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove non-content tags entirely
        for tag in soup(["script", "style", "noscript", "head",
                         "nav", "footer", "aside", "form",
                         "header", "meta", "link"]):
            tag.decompose()

        # Collapse whitespace
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)

        return _truncate_output(cleaned)

    except Exception as exc:
        return f"[Error] Failed to fetch URL: {exc}"
