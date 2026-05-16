import re
import json
import time
from typing import Optional
from langchain_core.tools import tool
from ..browser_tools import BROWSER_SESSIONS

@tool
def browser_security_audit(session_id: str, tab_index: Optional[int] = None) -> str:
    """Performs a comprehensive security header audit on the current page.
    Checks for critical protections like CSP, HSTS, X-Frame-Options, and XSS Protection.
    Args:
        session_id: The ID of the session to audit.
        tab_index: Optional index of the tab to audit. If not provided, the active tab is used.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    try:
        # 1. Get current URL
        url_info = session._run_task("get_view", "url", tab_index=tab_index)
        current_url = url_info.get("url", "")
        
        # 2. Extract headers for the current URL from network logs
        headers = {}
        for log in reversed(session.network_logs):
            if log.get("type") == "response" and log.get("url") == current_url:
                headers = log.get("headers", {})
                break
        
        # 3. Analyze Headers
        checks = {
            "Content-Security-Policy (CSP)": "content-security-policy" in headers or "x-webkit-csp" in headers,
            "Strict-Transport-Security (HSTS)": "strict-transport-security" in headers,
            "X-Frame-Options (Clickjacking)": "x-frame-options" in headers,
            "X-Content-Type-Options": "x-content-type-options" in headers,
            "Referrer-Policy": "referrer-policy" in headers,
            "Permissions-Policy": "permissions-policy" in headers or "feature-policy" in headers
        }
        
        report = f"--- SECURITY HEADER AUDIT: {current_url} ---\n"
        missing = []
        for name, present in checks.items():
            status = "✅ PRESENT" if present else "❌ MISSING"
            report += f"- {name}: {status}\n"
            if not present: missing.append(name)
            
        if missing:
            report += f"\n[ADVICE] This site is missing {len(missing)} critical security headers. This increases the attack surface for XSS, Clickjacking, and Sniffing attacks."
        else:
            report += "\n[INFO] All primary security headers are present. Good security posture."
            
        return report
    except Exception as e: return f"[ERROR] Security audit failed: {str(e)}"

@tool
def browser_extract_endpoints(session_id: str, tab_index: Optional[int] = None) -> str:
    """Scans all discovered JavaScript assets for potential API endpoints and hidden URLs.
    Useful for discovering unlinked resources and internal API paths.
    Args:
        session_id: The ID of the active session.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    try:
        js_urls = []
        for log in session.network_logs:
            url = log.get("url", "")
            if ".js" in url and url not in js_urls:
                js_urls.append(url)
        
        if not js_urls: return "[INFO] No JavaScript files discovered in the current session logs."
        
        report = f"--- DISCOVERED ENDPOINTS (from {len(js_urls)} JS files) ---\n"
        report += "[NOTE] Returning discovery report. Use 'fetch_url' on individual assets for full content analysis.\n\n"
        for url in js_urls: report += f"- {url}\n"
        
        return report
    except Exception as e: return f"[ERROR] Endpoint extraction failed: {str(e)}"

@tool
def browser_analyze_waf(session_id: str) -> str:
    """Detects the presence of Web Application Firewalls (WAFs) and DDoS protection services.
    Args:
        session_id: The ID of the session to check.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    waf_signatures = {
        "Cloudflare": ["cf-ray", "cloudflare", "__cfduid"],
        "Akamai": ["akamai", "edge_suite", "x-akamai-"],
        "Sucuri": ["x-sucuri-id", "sucuri"],
        "Incapsula/Imperva": ["visid_incap", "incap_ses", "x-iinfo"],
        "AWS WAF": ["x-amz-waf", "awswaf"],
        "F5 BIG-IP": ["x-wa-info", "f5_cspm"]
    }
    
    found_wafs = set()
    logs = session.network_logs
    
    for log in logs:
        # Check headers
        headers_str = str(log.get("headers", {})).lower()
        url_str = log.get("url", "").lower()
        
        for name, sigs in waf_signatures.items():
            if any(s.lower() in headers_str or s.lower() in url_str for s in sigs):
                found_wafs.add(name)
                
    if found_wafs:
        return f"[WAF DETECTED] This site appears to be protected by: {', '.join(found_wafs)}. Proceed with caution; aggressive scanning may result in IP blocking."
    return "[INFO] No obvious WAF signatures detected. However, a stealthy WAF may still be present."

@tool
def browser_map_params(session_id: str, tab_index: Optional[int] = None) -> str:
    """Identifies all interactive parameters (Forms, URL queries, Inputs) for potential fuzzing.
    Args:
        session_id: The ID of the session.
        tab_index: Optional index of the tab.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    try:
        res = session._run_task("eval", """
            () => {
                const params = [];
                // Query String
                const urlParams = new URLSearchParams(window.location.search);
                urlParams.forEach((val, key) => params.push({ type: 'URL_QUERY', name: key, value: val }));
                
                // Form Fields
                document.querySelectorAll('input, select, textarea').forEach(el => {
                    params.push({ type: 'FORM_FIELD', name: el.name || el.id, tag: el.tagName, input_type: el.type });
                });
                
                // Buttons & Clickables
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    params.push({ type: 'INTERACTIVE', name: el.innerText.trim() || el.id, tag: el.tagName });
                });
                
                return params;
            }
        """, tab_index=tab_index)
        
        if not res: return "[INFO] No interactive parameters discovered on this page."
        
        report = "--- PARAMETER & ATTACK SURFACE MAP ---\n"
        for p in res:
            report += f"- [{p['type']}] Name: {p['name']} | Tag: {p['tag']}"
            if 'input_type' in p: report += f" | Type: {p['input_type']}"
            report += "\n"
            
        return report
    except Exception as e: return f"[ERROR] Parameter mapping failed: {str(e)}"

@tool
def browser_fuzz_params(session_id: str, payload: str, tab_index: Optional[int] = None) -> str:
    """Automatically injects a security payload into all discovered inputs and textareas.
    After injection, it checks the page for 'reflections' (where the payload appears in the HTML).
    This is a primary method for discovering Cross-Site Scripting (XSS) vulnerabilities.
    Args:
        session_id: The ID of the session.
        payload: The test string/payload to inject (e.g., '<u>test</u>' or '{{7*7}}').
        tab_index: Optional tab index.
    """
    session = BROWSER_SESSIONS.get(session_id)
    if not session: return f"[ERROR] Session {session_id} not found."
    
    try:
        # 1. Inject payload into all inputs and trigger events
        injection_js = f"""
            () => {{
                const payload = {json.dumps(payload)};
                const inputs = document.querySelectorAll('input, textarea, [contenteditable="true"]');
                let count = 0;
                inputs.forEach(el => {{
                    if (el.type !== 'submit' && el.type !== 'button') {{
                        el.value = payload;
                        if (el.contentEditable === 'true') el.innerText = payload;
                        // Trigger events to bypass framework listeners
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        count++;
                    }}
                }});
                return count;
            }}
        """
        injected_count = session._run_task("eval", injection_js, tab_index=tab_index)
        
        # 2. Wait a moment for any async framework updates
        time.sleep(1)
        
        # 3. Check for reflections
        reflection_js = f"""
            () => {{
                const payload = {json.dumps(payload)};
                const reflections = [];
                
                // Check if rendered in DOM (XSS indicator)
                const bodyText = document.body.innerHTML;
                if (bodyText.includes(payload)) {{
                    reflections.push({{ type: 'DOM_INNER_HTML', context: 'Payload found raw in HTML' }});
                }}
                
                // Check if payload is actually "alive" (e.g. if we injected <u> and it's an underline element)
                // This is a bit complex, but we can check if any element's outerHTML contains it
                return reflections;
            }}
        """
        reflections = session._run_task("eval", reflection_js, tab_index=tab_index)
        
        report = f"--- FUZZING REPORT (Payload: {payload}) ---\n"
        report += f"- Injected into {injected_count} elements.\n"
        if reflections:
            report += f"⚠️ REFLECTION DETECTED! The payload was found in the page source.\n"
            for r in reflections:
                report += f"  - [{r['type']}] {r['context']}\n"
            report += "[ADVICE] This page may be vulnerable to XSS. Analyze the reflection context to confirm if characters are escaped."
        else:
            report += "✅ No immediate reflections detected in the DOM. The site may be properly escaping inputs."
            
        return report
    except Exception as e: return f"[ERROR] Fuzzing failed: {str(e)}"
