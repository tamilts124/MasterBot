import warnings
import urllib.request
from ddgs import DDGS
from langchain_core.tools import tool
from .common import _truncate_output

@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Perform a live web search using DuckDuckGo to find information, documentation, or code examples.
    Args:
        query: The search term or question to find on the web.
        max_results: The maximum number of search results to return (default 5).
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found."
            
            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title', 'N/A')}\nURL: {r.get('href', 'N/A')}\nSnippet: {r.get('body', 'N/A')}\n")
            
            return _truncate_output("\n---\n".join(formatted_results))
    except Exception as e:
        return f"Error during search: {str(e)}"

@tool
def fetch_url(url: str) -> str:
    """Download and read the raw text content of a specific web URL.
    Use this to read documentation, API references, or source code from websites found during search.
    Args:
        url: The full HTTP/HTTPS URL to fetch.
    """
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8", errors="ignore")
            return _truncate_output(content)
    except Exception as exc:
        return f"[Error] Failed to fetch URL: {exc}"
