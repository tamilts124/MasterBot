import os
import uuid
import time
import json
import threading
import queue
from typing import Dict, List, Optional, Any
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from langchain_core.tools import tool

class BrowserSession:
    """A thread-safe wrapper for Playwright sessions.
    Starts a dedicated background thread to own the Playwright instance,
    allowing access from any thread (useful for multi-threaded agent environments).
    """
    def __init__(self, headless: bool = True):
        self.id = str(uuid.uuid4())[:8]
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.active_page_index = 0
        self.network_logs = []
        self.console_logs = []
        self.running = True
        self.headless = headless
        
        # Start the dedicated Playwright thread
        self.thread = threading.Thread(
            target=self._playwright_worker, 
            args=(self.headless,), 
            name=f"Playwright-{self.id}",
            daemon=True
        )
        self.thread.start()
        
        # Wait for initialization to complete
        res = self._run_task("init")
        if isinstance(res, str) and res.startswith("[ERROR]"):
            raise RuntimeError(res)

    def _playwright_worker(self, headless: bool):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                
                # Setup context-level listeners
                context.on("request", lambda request: self.network_logs.append({
                    "type": "request", "method": request.method, "url": request.url, "time": time.time()
                }))
                context.on("response", lambda response: self.network_logs.append({
                    "type": "response", "status": response.status, "url": response.url, 
                    "headers": response.all_headers(), "time": time.time()
                }))

                pages: List[Page] = [context.new_page()]
                
                def setup_page_listeners(pge: Page):
                    pge.on("console", lambda msg: self.console_logs.append({
                        "type": msg.type, "text": msg.text, "url": pge.url, "time": time.time()
                    }))

                setup_page_listeners(pages[0])
                
                # Note: No put([SUCCESS]) here to avoid desync. The "init" task below will handle it.

                while self.running:
                    try:
                        # Get task from queue with timeout to check self.running
                        try:
                            task_data = self.task_queue.get(timeout=1.0)
                        except queue.Empty:
                            continue

                        action, args, kwargs = task_data
                        
                        if action == "stop":
                            self.result_queue.put("[SUCCESS]")
                            break
                        
                        # Execute the requested action
                        result = self._execute_action(action, args, kwargs, browser, context, pages, setup_page_listeners)
                        self.result_queue.put(result)
                        
                    except Exception as e:
                        self.result_queue.put(f"[ERROR] Worker action failed: {str(e)}")
                
                context.close()
                browser.close()
        except Exception as e:
            self.result_queue.put(f"[ERROR] Playwright thread crashed: {str(e)}")

    def _execute_action(self, action, args, kwargs, browser, context, pages, setup_listeners):
        # Internal router for browser actions
        try:
            tab_index = kwargs.get("tab_index")
            if tab_index is None:
                tab_index = self.active_page_index
            
            if action == "new_tab":
                p = context.new_page()
                setup_listeners(p)
                pages.append(p)
                self.active_page_index = len(pages) - 1
                return f"[SUCCESS] New tab index: {self.active_page_index}"
            
            if action == "close_tab":
                idx = args[0]
                if len(pages) <= 1: return "[ERROR] Cannot close last tab."
                p = pages.pop(idx)
                p.close()
                if self.active_page_index >= len(pages): self.active_page_index = len(pages) - 1
                return "[SUCCESS]"

            # Most actions target a specific page
            page = pages[tab_index]
            
            if action == "navigate":
                url = args[0]
                page.goto(url, wait_until="networkidle")
                return f"[SUCCESS] Title: {page.title()}"
            
            if action == "click":
                page.click(args[0], timeout=15000)
                return "[SUCCESS]"
            
            if action == "type":
                page.fill(args[0], args[1], timeout=15000)
                if kwargs.get("press_enter"): page.press(args[0], "Enter")
                return "[SUCCESS]"
            
            if action == "get_view":
                mode = args[0]
                if mode == "text": return page.inner_text("body")[:20000]
                if mode == "html": return page.content()
                if mode == "elements":
                    res = page.evaluate("() => { const els = []; document.querySelectorAll('button, a, input, select, textarea, [role=\"button\"]').forEach(el => { if (el.offsetWidth > 0 && el.offsetHeight > 0) els.push({ tag: el.tagName, text: el.innerText.trim() || el.value || el.placeholder || el.ariaLabel || \"\", selector: el.id ? `#${el.id}` : (el.innerText ? `text=\"${el.innerText.split('\\n')[0].trim()}\"` : \"\") }); }); return els.slice(0, 100); }")
                    return res
                return {"url": page.url, "title": page.title()}

            if action == "wait_for":
                page.wait_for_selector(args[0], state=kwargs.get("state", "visible"), timeout=kwargs.get("timeout", 30000))
                return "[SUCCESS]"

            if action == "scroll":
                d, a = args[0], args[1]
                if d == "down": page.evaluate(f"window.scrollBy(0, {a})")
                elif d == "up": page.evaluate(f"window.scrollBy(0, {-a})")
                elif d == "top": page.evaluate("window.scrollTo(0, 0)")
                elif d == "bottom": page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return "[SUCCESS]"

            if action == "screenshot":
                path = args[0]
                page.screenshot(path=path)
                return "[SUCCESS]"

            if action == "eval":
                return page.evaluate(args[0])

            if action == "cookies_get":
                return context.cookies()
            
            if action == "cookies_set":
                cookies = args[0]
                if not isinstance(cookies, list):
                    return "[ERROR] cookies_set: expected a list of cookie objects."
                context.add_cookies(cookies)
                return "[SUCCESS]"

            if action == "ls_get":
                k = args[0]
                if k: return page.evaluate(f"window.localStorage.getItem('{k}')")
                return page.evaluate("JSON.stringify(window.localStorage)")

            if action == "ls_set":
                page.evaluate(f"window.localStorage.setItem('{args[0]}', '{args[1]}')")
                return "[SUCCESS]"
            
            if action == "accessibility":
                if hasattr(page, "accessibility"):
                    return page.accessibility.snapshot()
                return "[ERROR] Accessibility tree not supported in this browser version."

            if action == "get_state":
                # Returns current URLs of all tabs to allow restoration
                return [p.url for p in pages]

            if action == "init":
                return "[SUCCESS]"
            
            if action == "stop":
                return "[SUCCESS]"
            
            return f"[ERROR] Unknown action: {action}"
        except Exception as e:
            return f"[ERROR] {str(e)}"

    def _run_task(self, action: str, *args, **kwargs) -> Any:
        # Send task and wait for result
        self.task_queue.put((action, args, kwargs))
        return self.result_queue.get()

    def close(self):
        self.running = False
        self.task_queue.put(("stop", (), {}))
        self.thread.join(timeout=2.0)

# Registry
BROWSER_SESSIONS: Dict[str, BrowserSession] = {}

@tool
def start_browser_session(headless: bool = True) -> str:
    """Starts a new persistent browser session with a single initial tab.
    Args:
        headless: If True, runs the browser in the background. If False, a visible window will appear (useful for debugging).
    Returns:
        A unique session_id required for all other browser tools.
    """
    try:
        session = BrowserSession(headless=headless)
        BROWSER_SESSIONS[session.id] = session
        return f"[SUCCESS] Browser session started. ID: {session.id}"
    except Exception as e: return f"[ERROR] Failed to start browser: {str(e)}"

@tool
def list_browser_sessions() -> str:
    """Lists all active browser sessions and their currently open tabs.
    Use this to retrieve session_ids if you lose track or to check the status of multiple agents.
    """
    if not BROWSER_SESSIONS: return "[INFO] No active browser sessions."
    report = "--- ACTIVE BROWSER SESSIONS ---\n"
    for sid, session in BROWSER_SESSIONS.items():
        report += f"- Session ID: {sid}\n"
    return report

@tool
def browser_new_tab(session_id: str, url: Optional[str] = None) -> str:
    """Opens a new tab in an existing browser session.
    Args:
        session_id: The ID of the session to add a tab to.
        url: Optional URL to navigate to immediately after opening.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    res = session._run_task("new_tab")
    if url and "[SUCCESS]" in str(res):
        browser_navigate(session_id, url)
    return str(res)

@tool
def browser_switch_tab(session_id: str, tab_index: int) -> str:
    """Switches the active focus of the session to a specific tab.
    Args:
        session_id: The ID of the session.
        tab_index: The numeric index of the tab (starting from 0). Use 'list_browser_sessions' to find indices.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    session.active_page_index = tab_index
    return f"[SUCCESS] Active tab set to {tab_index}"

@tool
def browser_close_tab(session_id: str, tab_index: int) -> str:
    """Closes a specific tab within a session.
    Args:
        session_id: The ID of the session.
        tab_index: The numeric index of the tab to close.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("close_tab", tab_index))

@tool
def browser_navigate(session_id: str, url: str, tab_index: Optional[int] = None) -> str:
    """Navigates a tab to a specific URL.
    Args:
        session_id: The ID of the session.
        url: The destination URL.
        tab_index: Optional index of the tab to navigate. If not provided, the currently active tab is used.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    url = url.replace(" ", "")
    if not url.startswith(("http://", "https://")): url = "https://" + url
    return str(session._run_task("navigate", url, tab_index=tab_index))

@tool
def browser_wait_for(session_id: str, selector: str, state: str = "visible", timeout: int = 30000, tab_index: Optional[int] = None) -> str:
    """Explicitly waits for an element to reach a specific state. Use this to handle slow-loading content.
    Args:
        session_id: The ID of the session.
        selector: CSS or text selector of the element to wait for.
        state: The state to wait for: 'visible', 'hidden' (disappeared), 'attached', or 'detached'.
        timeout: Maximum time to wait in milliseconds (default 30,000ms).
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("wait_for", selector, tab_index=tab_index, state=state, timeout=timeout))

@tool
def browser_scroll(session_id: str, direction: str = "down", amount: int = 500, tab_index: Optional[int] = None) -> str:
    """Scrolls the page in the specified direction. Use this for infinite-scroll or lazy-loaded content.
    Args:
        session_id: The ID of the session.
        direction: 'down', 'up', 'top' (scroll to start), or 'bottom' (scroll to end).
        amount: Number of pixels to scroll (only used for 'down' and 'up').
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("scroll", direction, amount, tab_index=tab_index))

@tool
def browser_get_view(session_id: str, tab_index: Optional[int] = None, mode: str = "text") -> str:
    """Retrieves the current content or structure of a tab.
    Args:
        session_id: The ID of the session.
        tab_index: Optional index of the tab.
        mode: 
            'text': Returns all visible text on the page (best for general analysis).
            'elements': Returns a list of interactive elements (buttons, links) with their selectors.
            'html': Returns the full raw HTML source code.
            'url': Returns just the current URL and Page Title.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    res = session._run_task("get_view", mode, tab_index=tab_index)
    if mode == "elements":
        if not isinstance(res, list): return str(res)
        report = "--- INTERACTIVE ELEMENTS ---\n"
        for el in res: report += f"- [{el['tag']}] \"{el['text']}\" | Selector: {el['selector'] or 'N/A'}\n"
        return report
    return str(res)

@tool
def browser_get_accessibility_tree(session_id: str, tab_index: Optional[int] = None) -> str:
    """Returns a simplified semantic map of the page (Accessibility Tree). 
    Use this to understand the purpose of complex UI elements and their roles (buttons, menus, regions).
    Args:
        session_id: The ID of the session.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    res = session._run_task("accessibility", tab_index=tab_index)
    return json.dumps(res, indent=2)

@tool
def browser_click(session_id: str, selector: str, tab_index: Optional[int] = None) -> str:
    """Clicks an element on the page.
    Args:
        session_id: The ID of the session.
        selector: CSS or text selector of the element to click (e.g., '#submit', 'text="Login"').
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("click", selector, tab_index=tab_index))

@tool
def browser_type(session_id: str, selector: str, text: str, tab_index: Optional[int] = None, press_enter: bool = True) -> str:
    """Types text into an input field.
    Args:
        session_id: The ID of the session.
        selector: CSS or text selector of the input field.
        text: The string to type.
        tab_index: Optional index of the tab.
        press_enter: If True, presses the 'Enter' key immediately after typing.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("type", selector, text, tab_index=tab_index, press_enter=press_enter))

@tool
def browser_eval(session_id: str, script: str, tab_index: Optional[int] = None) -> str:
    """Executes custom JavaScript code in the browser context and returns the result.
    Args:
        session_id: The ID of the session.
        script: The JavaScript code to execute.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    res = session._run_task("eval", script, tab_index=tab_index)
    return json.dumps(res, indent=2)

@tool
def browser_save_cookies(session_id: str, filename: str = "browser_cookies.json") -> str:
    """Saves all cookies from the current session to a file. Use this to persist logins.
    Args:
        session_id: The ID of the session.
        filename: Name of the JSON file to save (stored in 'browser_outputs').
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    cookies = session._run_task("cookies_get")
    os.makedirs("browser_outputs", exist_ok=True)
    path = os.path.join("browser_outputs", filename)
    with open(path, "w") as f: json.dump(cookies, f)
    return f"[SUCCESS] Cookies saved to {path}"

@tool
def browser_load_cookies(session_id: str, filename: str = "browser_cookies.json") -> str:
    """Loads previously saved cookies into the current session to restore a login state.
    Args:
        session_id: The ID of the session.
        filename: Name of the JSON file to load from.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    path = os.path.join("browser_outputs", filename)
    if not os.path.exists(path): return f"[ERROR] Cookie file {path} not found."
    with open(path, "r") as f: cookies = json.load(f)
    return str(session._run_task("cookies_set", cookies))

@tool
def browser_get_local_storage(session_id: str, key: Optional[str] = None, tab_index: Optional[int] = None) -> str:
    """Retrieves items from the browser's localStorage.
    Args:
        session_id: The ID of the session.
        key: Optional specific key to retrieve. If None, returns all items in localStorage.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("ls_get", key, tab_index=tab_index))

@tool
def browser_set_local_storage(session_id: str, key: str, value: str, tab_index: Optional[int] = None) -> str:
    """Sets a value in the browser's localStorage.
    Args:
        session_id: The ID of the session.
        key: The storage key name.
        value: The string value to store.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    return str(session._run_task("ls_set", key, value, tab_index=tab_index))

@tool
def browser_get_network_logs(session_id: str, limit: int = 30) -> str:
    """Retrieves a chronological list of recent network requests and responses (DevTools Network view).
    Args:
        session_id: The ID of the session.
        limit: Number of recent logs to retrieve (default 30).
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    logs = session.network_logs[-limit:]
    report = f"--- NETWORK LOGS (Recent {len(logs)}) ---\n"
    for log in logs:
        if log["type"] == "request": report += f"[REQ] {log['method']} {log['url']}\n"
        else: report += f"[RES] {log['status']} {log['url']}\n"
    return report

@tool
def browser_get_console_logs(session_id: str, limit: int = 30) -> str:
    """Retrieves recent console logs (log, error, warning) from the browser.
    Args:
        session_id: The ID of the session.
        limit: Number of recent logs to retrieve (default 30).
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    logs = session.console_logs[-limit:]
    report = f"--- CONSOLE LOGS (Recent {len(logs)}) ---\n"
    for log in logs:
        report += f"[{log['type'].upper()}] ({log['url']}): {log['text']}\n"
    return report

@tool
def browser_screenshot(session_id: str, tab_index: Optional[int] = None, filename: str = "browser_shot.png") -> str:
    """Takes a visual screenshot of a specific tab.
    Args:
        session_id: The ID of the session.
        tab_index: Optional index of the tab to capture.
        filename: Name of the image file to save (stored in 'browser_outputs').
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    os.makedirs("browser_outputs", exist_ok=True)
    path = os.path.join("browser_outputs", filename)
    res = session._run_task("screenshot", path, tab_index=tab_index)
    return f"[SUCCESS] Saved to {path}" if "[SUCCESS]" in str(res) else str(res)

@tool
def browser_set_visibility(session_id: str, headless: bool) -> str:
    """Switches the browser between headless and visible mode. 
    Warning: This will restart the browser, but will attempt to restore the current tabs and cookies.
    Args:
        session_id: The ID of the session.
        headless: If True, makes the browser invisible. If False, makes it visible.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    try:
        # 1. Capture State
        urls = session._run_task("get_state")
        cookies = session._run_task("cookies_get")
        active_tab = session.active_page_index
        
        # 2. Shutdown
        session.close()
        
        # 3. Relaunch
        new_session = BrowserSession(headless=headless)
        new_session.id = session.id # Keep the same ID
        BROWSER_SESSIONS[session.id] = new_session
        
        # 4. Restore State
        new_session._run_task("cookies_set", cookies)
        for i, url in enumerate(urls):
            if i == 0:
                new_session._run_task("navigate", url, tab_index=0)
            else:
                # new_tab logic
                new_session._run_task("new_tab")
                new_session._run_task("navigate", url, tab_index=i)
        
        new_session.active_page_index = active_tab
        
        mode = "HEADLESS" if headless else "VISIBLE"
        return f"[SUCCESS] Browser session {session_id} is now {mode}. Tabs and cookies restored."
    except Exception as e:
        return f"[ERROR] Visibility switch failed: {str(e)}"

@tool
def stop_browser_session(session_id: str) -> str:
    """Closes all tabs and terminates the browser session, freeing up system resources.
    Args:
        session_id: The ID of the session to terminate.
    """
    session = BROWSER_SESSIONS.pop(session_id, None)
    if session:
        session.close()
        return f"[SUCCESS] Session {session_id} terminated."
    return f"[ERROR] Session {session_id} not found."
