import shutil
import socket
import ssl
import json
import datetime
from typing import Optional
from langchain_core.tools import tool
from ..interactive_tools import start_interactive_process
from ..common import _truncate_output


def _check_exec(executable: str) -> Optional[str]:
    """Check if executable exists in PATH."""
    if not shutil.which(executable):
        return f"[ERROR] '{executable}' not found in system PATH. Please install it to use this tool."
    return None


# ─── existing tools ────────────────────────────────────────────────────────────

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


# ─── new tools ─────────────────────────────────────────────────────────────────

@tool
def dns_lookup(domain: str, record_type: str = "A") -> str:
    """Resolve DNS records for a domain. Supports A, AAAA, MX, TXT, NS, CNAME, SOA records.
    Useful for recon, SPF/DMARC checks, mail server discovery, and IP resolution.
    Uses dnspython if available, falls back to stdlib socket for A/AAAA records.
    Args:
        domain: The domain to query (e.g., 'google.com').
        record_type: DNS record type — A, AAAA, MX, TXT, NS, CNAME, SOA (default: A).
    """
    record_type = record_type.upper().strip()
    supported = {"A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA"}
    if record_type not in supported:
        return f"[ERROR] Unsupported record type '{record_type}'. Supported: {', '.join(sorted(supported))}"

    # Try dnspython first (richer output)
    try:
        import dns.resolver
        import dns.exception

        resolver = dns.resolver.Resolver()
        resolver.timeout = 10
        resolver.lifetime = 10

        try:
            answers = resolver.resolve(domain, record_type)
        except dns.resolver.NXDOMAIN:
            return f"[ERROR] Domain '{domain}' does not exist (NXDOMAIN)."
        except dns.resolver.NoAnswer:
            return f"[INFO] No {record_type} records found for '{domain}'."
        except dns.resolver.NoNameservers:
            return f"[ERROR] No nameservers available for '{domain}'."
        except dns.exception.Timeout:
            return f"[ERROR] DNS query timed out for '{domain}'."

        lines = [f"DNS {record_type} records for {domain}:"]
        for rdata in answers:
            if record_type == "MX":
                lines.append(f"  priority={rdata.preference}  exchange={rdata.exchange.to_text().rstrip('.')}")
            elif record_type == "SOA":
                lines.append(
                    f"  mname={rdata.mname.to_text().rstrip('.')}  rname={rdata.rname.to_text().rstrip('.')}"
                    f"  serial={rdata.serial}  refresh={rdata.refresh}  retry={rdata.retry}"
                    f"  expire={rdata.expire}  minimum={rdata.minimum}"
                )
            else:
                lines.append(f"  {rdata.to_text()}")
        lines.append(f"\nTTL: {answers.rrset.ttl}s  |  Nameserver: {resolver.nameservers[0]}")
        return _truncate_output("\n".join(lines))

    except ImportError:
        pass  # fall through to stdlib

    # Stdlib fallback — only works for A / AAAA
    if record_type not in ("A", "AAAA"):
        return (
            f"[ERROR] 'dnspython' is not installed. Install it with: pip install dnspython\n"
            f"Stdlib fallback only supports A and AAAA records, not {record_type}."
        )
    try:
        family = socket.AF_INET6 if record_type == "AAAA" else socket.AF_INET
        results = socket.getaddrinfo(domain, None, family)
        ips = list({r[4][0] for r in results})
        lines = [f"DNS {record_type} records for {domain} (stdlib fallback — install dnspython for full support):"]
        for ip in ips:
            lines.append(f"  {ip}")
        return "\n".join(lines)
    except socket.gaierror as e:
        return f"[ERROR] DNS lookup failed for '{domain}': {e}"


@tool
def ssl_inspect(domain: str, port: int = 443, timeout: int = 10) -> str:
    """Inspect the SSL/TLS certificate of a domain.
    Returns expiry date, issuer, subject, SANs, TLS version, and cipher suite.
    Useful for recon, detecting expired certificates, and checking TLS configuration.
    Args:
        domain: The hostname to inspect (e.g., 'google.com').
        port: Port to connect on (default: 443).
        timeout: Connection timeout in seconds (default: 10).
    """
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as tls_sock:
                cert = tls_sock.getpeercert()
                tls_version = tls_sock.version()
                cipher_name, cipher_proto, cipher_bits = tls_sock.cipher()

        # Parse subject
        subject = {}
        for item in cert.get("subject", []):
            k, v = item[0]
            subject[k] = v

        # Parse issuer
        issuer = {}
        for item in cert.get("issuer", []):
            k, v = item[0]
            issuer[k] = v

        # Parse SANs
        sans = []
        for san_type, san_value in cert.get("subjectAltName", []):
            sans.append(f"{san_type}:{san_value}")

        # Parse expiry
        not_after_str = cert.get("notAfter", "")
        not_before_str = cert.get("notBefore", "")
        try:
            fmt = "%b %d %H:%M:%S %Y %Z"
            not_after = datetime.datetime.strptime(not_after_str, fmt)
            not_before = datetime.datetime.strptime(not_before_str, fmt)
            days_left = (not_after - datetime.datetime.utcnow()).days
            expiry_status = "✅ VALID" if days_left > 0 else "❌ EXPIRED"
            if 0 < days_left <= 30:
                expiry_status = f"⚠️ EXPIRING SOON ({days_left} days)"
        except Exception:
            not_after = not_after_str
            not_before = not_before_str
            days_left = "?"
            expiry_status = "unknown"

        lines = [
            f"--- SSL/TLS INSPECTION: {domain}:{port} ---",
            f"Status:       {expiry_status}",
            f"TLS Version:  {tls_version}",
            f"Cipher:       {cipher_name} ({cipher_proto}, {cipher_bits}-bit)",
            f"",
            f"Subject:",
            f"  CN:         {subject.get('commonName', 'N/A')}",
            f"  O:          {subject.get('organizationName', 'N/A')}",
            f"  C:          {subject.get('countryName', 'N/A')}",
            f"",
            f"Issuer:",
            f"  CN:         {issuer.get('commonName', 'N/A')}",
            f"  O:          {issuer.get('organizationName', 'N/A')}",
            f"",
            f"Validity:",
            f"  Not Before: {not_before}",
            f"  Not After:  {not_after}",
            f"  Days Left:  {days_left}",
            f"",
            f"SANs ({len(sans)} total):",
        ]
        for san in sans[:20]:
            lines.append(f"  {san}")
        if len(sans) > 20:
            lines.append(f"  ... and {len(sans) - 20} more")

        return _truncate_output("\n".join(lines))

    except ssl.SSLCertVerificationError as e:
        return f"[ERROR] SSL certificate verification failed for {domain}:{port} — {e}"
    except ssl.SSLError as e:
        return f"[ERROR] SSL error for {domain}:{port} — {e}"
    except socket.timeout:
        return f"[ERROR] Connection timed out connecting to {domain}:{port}"
    except ConnectionRefusedError:
        return f"[ERROR] Connection refused to {domain}:{port} — port may be closed."
    except OSError as e:
        return f"[ERROR] Network error for {domain}:{port} — {e}"


@tool
def port_scan(host: str, ports: str = "21,22,23,25,53,80,110,143,443,445,3306,3389,5432,6379,8080,8443,27017", timeout: float = 1.0) -> str:
    """Scan a host for open TCP ports and grab service banners where possible.
    Returns open ports with service name guesses and any banners received.
    Args:
        host: The hostname or IP to scan (e.g., 'example.com' or '192.168.1.1').
        ports: Comma-separated port numbers or ranges like '80,443,8000-8010' (default: common ports).
        timeout: Seconds to wait per port connection attempt (default: 1.0).
    """
    # Resolve host to IP first
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror as e:
        return f"[ERROR] Could not resolve host '{host}': {e}"

    # Parse port spec into a list of ints
    port_list = []
    for part in ports.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                port_list.extend(range(int(start), int(end) + 1))
            except ValueError:
                return f"[ERROR] Invalid port range: '{part}'"
        else:
            try:
                port_list.append(int(part))
            except ValueError:
                return f"[ERROR] Invalid port number: '{part}'"

    if not port_list:
        return "[ERROR] No valid ports specified."
    if len(port_list) > 1000:
        return f"[ERROR] Too many ports ({len(port_list)}). Limit to 1000 per scan."

    # Common port → service name map
    service_map = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
        465: "SMTPS", 587: "SMTP-TLS", 993: "IMAPS", 995: "POP3S",
        1433: "MSSQL", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
        5900: "VNC", 6379: "Redis", 8080: "HTTP-ALT", 8443: "HTTPS-ALT",
        8888: "HTTP-DEV", 9200: "Elasticsearch", 27017: "MongoDB",
    }

    open_ports = []
    closed_count = 0

    for port in sorted(set(port_list)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                result = s.connect_ex((ip, port))
                if result == 0:
                    # Try to grab a banner (non-blocking read)
                    banner = ""
                    try:
                        s.settimeout(2.0)
                        raw = s.recv(256)
                        banner = raw.decode("utf-8", errors="replace").strip().replace("\r\n", " ").replace("\n", " ")[:120]
                    except Exception:
                        pass
                    service = service_map.get(port, "unknown")
                    open_ports.append((port, service, banner))
                else:
                    closed_count += 1
        except Exception:
            closed_count += 1

    lines = [
        f"--- PORT SCAN: {host} ({ip}) ---",
        f"Scanned: {len(set(port_list))} ports  |  Open: {len(open_ports)}  |  Closed/Filtered: {closed_count}",
        "",
    ]

    if not open_ports:
        lines.append("[INFO] No open ports found.")
    else:
        lines.append(f"{'PORT':<8} {'SERVICE':<16} {'BANNER'}")
        lines.append("-" * 60)
        for port, service, banner in open_ports:
            banner_display = f"  {banner}" if banner else ""
            lines.append(f"{port:<8} {service:<16}{banner_display}")

    return _truncate_output("\n".join(lines))


@tool
def start_sqlmap(url: str, params: Optional[str] = None, level: int = 1, risk: int = 1, extra_flags: Optional[str] = None) -> str:
    """Starts a background SQLMap process to test a URL for SQL injection vulnerabilities.
    IMPORTANT: This runs in the BACKGROUND. Use 'list_interactive_processes' to check status
    and 'get_process_history' with the Process ID to review findings.
    SQLMap must be installed and available as 'sqlmap' in PATH (or as 'python sqlmap.py').
    Args:
        url: The target URL to test (e.g., 'http://example.com/page?id=1').
        params: Optional. Specific parameter(s) to test (e.g., 'id' or 'id,name'). Tests all if omitted.
        level: Crawl/test level 1-5 (default: 1 — fastest, least noise).
        risk: Risk level 1-3 (default: 1 — safe payloads only).
        extra_flags: Optional additional sqlmap flags as a string (e.g., '--dbs --batch').
    """
    sqlmap_cmd = shutil.which("sqlmap")
    if not sqlmap_cmd:
        return (
            "[ERROR] 'sqlmap' not found in PATH.\n"
            "Install: pip install sqlmap  or  git clone https://github.com/sqlmapproject/sqlmap"
        )

    if level < 1 or level > 5:
        return "[ERROR] level must be between 1 and 5."
    if risk < 1 or risk > 3:
        return "[ERROR] risk must be between 1 and 3."

    cmd = f'sqlmap -u "{url}" --level={level} --risk={risk} --batch --no-color'
    if params:
        cmd += f" -p {params}"
    if extra_flags:
        cmd += f" {extra_flags.strip()}"

    return start_interactive_process.invoke(cmd)
