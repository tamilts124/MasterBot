import shutil
from typing import Optional
from langchain_core.tools import tool
from ..interactive_tools import start_interactive_process

def _check_exec(executable: str) -> Optional[str]:
    """Check if executable exists in PATH."""
    if not shutil.which(executable):
        return f"[ERROR] '{executable}' not found in system PATH. Please install it to use this tool."
    return None

@tool
def start_subfinder(domain: str) -> str:
    """Starts a background Subfinder process to discover subdomains.
    IMPORTANT: This starts in the BACKGROUND. You must use 'list_interactive_processes' to see its status 
    and 'get_process_history' with its Process ID to review the discovered subdomains.
    Args:
        domain: The root domain to scan (e.g., 'google.com').
    """
    err = _check_exec("subfinder")
    if err: return err
    
    cmd = f"subfinder -d {domain} -silent"
    return start_interactive_process.invoke(cmd)

@tool
def start_httpx(target: str) -> str:
    """Starts a background Httpx process to probe for working HTTP services and tech stack.
    IMPORTANT: This starts in the BACKGROUND. Use 'list_interactive_processes' to check status 
    and 'get_process_history' to see the tech fingerprinting results later.
    Args:
        target: The target URL or domain to probe.
    """
    err = _check_exec("httpx")
    if err: return err
    
    cmd = f"httpx -u {target} -silent -td -title -sc -no-color"
    return start_interactive_process.invoke(cmd)

@tool
def start_nuclei_scan(target: str, templates: Optional[str] = None) -> str:
    """Starts a background Nuclei process for vulnerability scanning.
    IMPORTANT: Vulnerability scans take time and run in the BACKGROUND. 
    Review findings by using 'get_process_history' periodically. Use 'list_interactive_processes' to track all scans.
    Args:
        target: The target URL to scan.
        templates: Optional. Specific templates or tags to use (e.g., 'cves,exposures').
    """
    err = _check_exec("nuclei")
    if err: return err
    
    cmd = f"nuclei -u {target} -silent -no-color"
    if templates:
        cmd += f" -t {templates}"
    return start_interactive_process.invoke(cmd)

@tool
def start_paramspider(domain: str) -> str:
    """Starts a background ParamSpider process to find hidden parameters.
    IMPORTANT: This starts in the BACKGROUND. Use 'list_interactive_processes' to check status 
    and 'get_process_history' to see the discovered parameters once the scan progresses.
    Args:
        domain: The domain to fetch parameters for.
    """
    err = _check_exec("paramspider")
    if err: return err
    
    cmd = f"paramspider -d {domain} --silent"
    return start_interactive_process.invoke(cmd)
