#!/usr/bin/env python3
"""Keep a Let's Encrypt certificate on a Synology SRM router current.

Issues and renews the certificate with certbot using the DNS-01 challenge
through the Spaceship DNS API, then imports it into SRM through the
DSM-style web API whenever the router serves a different certificate.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path.home() / ".config" / "scriptoza" / "srm-cert-renew.conf"
STATE_DIR = Path.home() / ".local" / "state" / "scriptoza" / "srm-cert-renew"
REQUIRED_KEYS = (
    "DOMAIN",
    "DNS_ZONE",
    "SPACESHIP_API_KEY",
    "SPACESHIP_API_SECRET",
    "SRM_URL",
    "SRM_USER",
    "SRM_PASSWORD",
)
SPACESHIP_URL = "https://spaceship.dev/api/v1/dns/records/{zone}"
RESOLVERS = ("1.1.1.1", "8.8.8.8")
CERT_DESC = "scriptoza srm-cert-renew"
USER_AGENT = "scriptoza-srm-cert-renew/1.0"
HTTP_TIMEOUT = 30
TLS_TIMEOUT = 15
DIG_TIMEOUT = 15
CERTBOT_TIMEOUT = 1800
DNS_POLL_INTERVAL = 10
DNS_POLL_LIMIT = 600
SERVED_CHECK_LIMIT = 90
TWO_FACTOR_CODES = {403, 404, 406}
DRY_RUN_NOTICE = "DRY RUN: nothing will change. Use --run to apply changes."


class SrmError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def load_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"config file not found: {path} (see utils/srm-cert-renew.conf.example)")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        fail(f"config file {path} has mode {mode:04o}; it must be 0600 (chmod 600 {path})")
    config: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            fail(f"{path}:{number}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        config[key.strip()] = value
    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        fail(f"missing config keys in {path}: {', '.join(missing)}")
    domain = config["DOMAIN"].rstrip(".").lower()
    zone = config["DNS_ZONE"].rstrip(".").lower()
    if not domain.endswith("." + zone):
        fail("DOMAIN must be a subdomain of DNS_ZONE")
    config["DOMAIN"] = domain
    config["DNS_ZONE"] = zone
    config["SRM_URL"] = config["SRM_URL"].rstrip("/")
    return config


def record_name(config: dict[str, str]) -> str:
    label = config["DOMAIN"][: -len("." + config["DNS_ZONE"])]
    return f"_acme-challenge.{label}"


def spaceship_request(config: dict[str, str], method: str, body: Any) -> None:
    request = urllib.request.Request(
        SPACESHIP_URL.format(zone=config["DNS_ZONE"]),
        data=json.dumps(body).encode(),
        method=method,
        headers={
            "X-API-Key": config["SPACESHIP_API_KEY"],
            "X-API-Secret": config["SPACESHIP_API_SECRET"],
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            response.read()
    except urllib.error.HTTPError as error:
        raise SrmError(f"Spaceship {method} failed with HTTP {error.code}") from None
    except (urllib.error.URLError, OSError) as error:
        raise SrmError(f"Spaceship {method} failed: {error}") from None


def txt_values(resolver: str, name: str) -> set[str]:
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=5", "+tries=1", f"@{resolver}", "TXT", name],
            capture_output=True,
            text=True,
            timeout=DIG_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    values = set()
    for line in result.stdout.splitlines():
        parts = shlex.split(line) if line.strip() else []
        if parts:
            values.add("".join(parts))
    return values


def hook_auth(config: dict[str, str]) -> int:
    validation = os.environ.get("CERTBOT_VALIDATION")
    if not validation:
        fail("CERTBOT_VALIDATION is not set; this subcommand is called by certbot")
    name = record_name(config)
    fqdn = f"{name}.{config['DNS_ZONE']}"
    log(f"Creating TXT record {fqdn}")
    try:
        spaceship_request(
            config,
            "PUT",
            {"force": True, "items": [{"type": "TXT", "name": name, "value": validation, "ttl": 300}]},
        )
    except SrmError as error:
        fail(str(error))
    deadline = time.monotonic() + DNS_POLL_LIMIT
    while True:
        pending = [resolver for resolver in RESOLVERS if validation not in txt_values(resolver, fqdn)]
        if not pending:
            log(f"TXT record visible on {', '.join(RESOLVERS)}")
            return 0
        if time.monotonic() >= deadline:
            break
        log(f"Waiting for TXT record on {', '.join(pending)}")
        time.sleep(DNS_POLL_INTERVAL)
    log("TXT record not visible after 10 minutes; removing it")
    try:
        delete_txt(config, validation)
    except SrmError as error:
        log(f"WARNING: {error}")
    return 1


def delete_txt(config: dict[str, str], validation: str) -> None:
    spaceship_request(config, "DELETE", [{"type": "TXT", "name": record_name(config), "value": validation}])


def hook_cleanup(config: dict[str, str]) -> int:
    validation = os.environ.get("CERTBOT_VALIDATION")
    if not validation:
        fail("CERTBOT_VALIDATION is not set; this subcommand is called by certbot")
    log(f"Removing TXT record {record_name(config)}.{config['DNS_ZONE']}")
    try:
        delete_txt(config, validation)
    except SrmError as error:
        log(f"WARNING: {error}")
        return 1
    return 0


def lineage_dir() -> Path:
    return STATE_DIR / "config"


def live_files(domain: str) -> dict[str, Path]:
    live = lineage_dir() / "live" / domain
    return {
        "cert": live / "cert.pem",
        "chain": live / "chain.pem",
        "key": live / "privkey.pem",
    }


def pem_fingerprint(path: Path) -> str:
    text = path.read_text(encoding="ascii")
    end = "-----END CERTIFICATE-----"
    first = text[: text.index(end) + len(end)] + "\n"
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(first)).hexdigest()


def cert_days_left(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-in", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip().partition("=")[2]
    if result.returncode != 0 or not value:
        return None
    try:
        expires = ssl.cert_time_to_seconds(value)
    except ValueError:
        return None
    return (expires - time.time()) / 86400


def find_certbot() -> str | None:
    found = shutil.which("certbot")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "certbot"
    return str(fallback) if fallback.is_file() else None


def account_args(config: dict[str, str]) -> list[str]:
    email = config.get("ACME_EMAIL", "")
    if email:
        return ["--no-eff-email", "-m", email]
    return ["--register-unsafely-without-email"]


def run_certbot(config: dict[str, str], config_path: Path) -> None:
    certbot = find_certbot()
    if not certbot:
        raise SrmError("certbot not found; install it with: uv tool install certbot")
    for directory in (STATE_DIR, lineage_dir(), STATE_DIR / "work", STATE_DIR / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    hook = shlex.join([sys.executable, str(Path(__file__).resolve()), "--config", str(config_path)])
    command = [
        certbot,
        "certonly",
        "--non-interactive",
        "--agree-tos",
        *account_args(config),
        "--manual",
        "--preferred-challenges",
        "dns",
        "--manual-auth-hook",
        f"{hook} hook-auth",
        "--manual-cleanup-hook",
        f"{hook} hook-cleanup",
        "-d",
        config["DOMAIN"],
        "--cert-name",
        config["DOMAIN"],
        "--keep-until-expiring",
        "--config-dir",
        str(lineage_dir()),
        "--work-dir",
        str(STATE_DIR / "work"),
        "--logs-dir",
        str(STATE_DIR / "logs"),
    ]
    log("Running certbot")
    try:
        result = subprocess.run(command, timeout=CERTBOT_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SrmError("certbot timed out") from None
    if result.returncode != 0:
        raise SrmError(f"certbot failed with exit code {result.returncode}; see {STATE_DIR / 'logs'}")


def router_address(config: dict[str, str]) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(config["SRM_URL"])
    if parsed.scheme != "https" or not parsed.hostname:
        fail("SRM_URL must be an https:// URL")
    return parsed.hostname, parsed.port or 443


def tls_context(verify: bool) -> ssl.SSLContext:
    if verify:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def served_fingerprint(config: dict[str, str], verify: bool) -> str:
    host, port = router_address(config)
    with socket.create_connection((host, port), timeout=TLS_TIMEOUT) as sock:
        with tls_context(verify).wrap_socket(sock, server_hostname=config["DOMAIN"]) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise SrmError("router did not present a certificate")
    return hashlib.sha256(der).hexdigest()


class SrmClient:
    def __init__(self, config: dict[str, str], verify: bool) -> None:
        self.base = config["SRM_URL"]
        self.user = config["SRM_USER"]
        self.password = config["SRM_PASSWORD"]
        self.context = tls_context(verify)
        self.apis: dict[str, dict[str, Any]] = {}
        self.sid: str | None = None
        self.token: str | None = None
        self.auth_version = 0

    def request(self, path: str, data: bytes, content_type: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self.base}/webapi/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Content-Type": content_type, "User-Agent": USER_AGENT}
        if self.token:
            headers["X-SYNO-TOKEN"] = self.token
        request = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=self.context) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise SrmError(f"SRM request failed with HTTP {error.code}") from None
        except ssl.SSLCertVerificationError:
            raise SrmError(
                "router TLS certificate is not trusted for DOMAIN; "
                "use --allow-untrusted-router once for the bootstrap import"
            ) from None
        except (urllib.error.URLError, OSError) as error:
            raise SrmError(f"SRM request failed: {error}") from None
        try:
            return json.loads(body)
        except ValueError:
            raise SrmError("SRM returned a non-JSON response") from None

    def call(self, api: str, method: str, version: int, **params: str) -> dict[str, Any]:
        fields = {"api": api, "method": method, "version": str(version), **params}
        if self.sid:
            fields["_sid"] = self.sid
        return self.request(
            self.apis[api]["path"],
            urllib.parse.urlencode(fields).encode(),
            "application/x-www-form-urlencoded",
        )

    def discover(self) -> None:
        wanted = ("SYNO.API.Auth", "SYNO.Core.Certificate", "SYNO.Core.Certificate.CRT")
        fields = {"api": "SYNO.API.Info", "version": "1", "method": "query", "query": ",".join(wanted)}
        result = self.request("query.cgi", urllib.parse.urlencode(fields).encode(), "application/x-www-form-urlencoded")
        if not result.get("success"):
            raise SrmError(f"SYNO.API.Info query failed: {error_code(result)}")
        data = result.get("data") or {}
        missing = [api for api in wanted if api not in data]
        if missing:
            raise SrmError(f"router does not offer: {', '.join(missing)}")
        self.apis = {api: data[api] for api in wanted}
        for api in wanted:
            log(f"  {api}: path={self.apis[api]['path']} versions={self.apis[api]['minVersion']}-{self.apis[api]['maxVersion']}")
        self.auth_version = int(self.apis["SYNO.API.Auth"]["maxVersion"])

    def version(self, api: str) -> int:
        info = self.apis[api]
        return max(int(info["minVersion"]), min(1, int(info["maxVersion"])))

    def login(self) -> None:
        result = self.call(
            "SYNO.API.Auth",
            "login",
            self.auth_version,
            account=self.user,
            passwd=self.password,
            enable_syno_token="yes",
            format="sid",
            session="srm-cert-renew",
        )
        if not result.get("success"):
            code = error_code(result)
            if code in TWO_FACTOR_CODES:
                raise SrmError(
                    f"SRM login requires 2-step verification (error {code}); "
                    "use a dedicated admin account without 2FA"
                )
            raise SrmError(f"SRM login failed (error {code})")
        data = result.get("data") or {}
        self.sid = data.get("sid")
        self.token = data.get("synotoken")
        if not self.sid:
            raise SrmError("SRM login returned no session")
        log("Logged in to SRM")

    def logout(self) -> None:
        if not self.sid:
            return
        try:
            self.call("SYNO.API.Auth", "logout", self.auth_version, session="srm-cert-renew")
            log("Logged out of SRM")
        except SrmError as error:
            log(f"WARNING: SRM logout failed: {error}")
        self.sid = None
        self.token = None

    def target_certificate_id(self) -> str:
        result = self.call("SYNO.Core.Certificate.CRT", "list", self.version("SYNO.Core.Certificate.CRT"))
        if not result.get("success"):
            raise SrmError(f"certificate list failed (error {error_code(result)})")
        certificates = (result.get("data") or {}).get("certificates") or []
        for certificate in certificates:
            if certificate.get("desc") == CERT_DESC:
                log("Replacing the certificate entry created by this tool")
                return str(certificate.get("id", ""))
        for certificate in certificates:
            if certificate.get("is_default"):
                log("Replacing the current default certificate entry")
                return str(certificate.get("id", ""))
        log("No existing entry to replace; creating a new one")
        return ""

    def import_certificate(self, files: dict[str, Path], certificate_id: str) -> None:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for field, key in (("key", "key"), ("cert", "cert"), ("inter_cert", "chain")):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{files[key].name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n".encode()
                + files[key].read_bytes()
                + b"\r\n"
            )
        for field, value in (("id", certificate_id), ("desc", CERT_DESC), ("as_default", "true")):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode()
            )
        parts.append(f"--{boundary}--\r\n".encode())
        query = {
            "api": "SYNO.Core.Certificate",
            "method": "import",
            "version": str(self.version("SYNO.Core.Certificate")),
            "_sid": self.sid or "",
        }
        if self.token:
            query["SynoToken"] = self.token
        result = self.request(
            self.apis["SYNO.Core.Certificate"]["path"],
            b"".join(parts),
            f"multipart/form-data; boundary={boundary}",
            query,
        )
        if not result.get("success"):
            raise SrmError(f"certificate import failed (error {error_code(result)})")
        log("Certificate imported and set as default")


def error_code(result: dict[str, Any]) -> int | None:
    error = result.get("error")
    if isinstance(error, dict) and "code" in error:
        try:
            return int(error["code"])
        except (TypeError, ValueError):
            return None
    return None


def upload(config: dict[str, str], files: dict[str, Path], verify: bool) -> None:
    client = SrmClient(config, verify)
    log("SRM API discovery:")
    client.discover()
    try:
        client.login()
        client.import_certificate(files, client.target_certificate_id())
    finally:
        client.logout()


def wait_for_served(config: dict[str, str], expected: str) -> bool:
    deadline = time.monotonic() + SERVED_CHECK_LIMIT
    while True:
        try:
            if served_fingerprint(config, verify=True) == expected:
                return True
        except (OSError, ssl.SSLError, SrmError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(5)


def run(config: dict[str, str], config_path: Path, apply: bool, allow_untrusted: bool) -> int:
    domain = config["DOMAIN"]
    files = live_files(domain)
    log(f"Domain: {domain}")
    log(f"State directory: {STATE_DIR}")

    if files["cert"].is_file():
        days = cert_days_left(files["cert"])
        if days is None:
            log("Local certificate: present, expiry unreadable")
        else:
            log(f"Local certificate: {days:.1f} days left")
        needs_issue = days is None or days < 30
    else:
        log("Local certificate: none")
        needs_issue = True

    if apply:
        try:
            run_certbot(config, config_path)
        except SrmError as error:
            log(f"ERROR: {error}")
            if not files["cert"].is_file():
                return 1
            log("Continuing with the existing local certificate")
    elif needs_issue:
        log(f"Would run certbot (DNS-01 via Spaceship): create TXT {record_name(config)}.{config['DNS_ZONE']}, issue certificate, remove TXT")
    else:
        log("Would run certbot; it keeps the certificate until fewer than 30 days remain")

    if not files["cert"].is_file():
        log("Would import the new certificate into SRM after issuance")
        return 0

    local = pem_fingerprint(files["cert"])
    try:
        served = served_fingerprint(config, verify=False)
    except (OSError, ssl.SSLError, SrmError) as error:
        log(f"ERROR: cannot read the certificate served by the router: {error}")
        return 1
    log(f"Local certificate SHA-256:  {local}")
    log(f"Served certificate SHA-256: {served}")

    if served == local:
        log("Router serves the current certificate; nothing to do")
        return 0

    if not apply:
        log("Would import the local certificate into SRM and set it as default")
        return 0

    try:
        upload(config, files, verify=not allow_untrusted)
    except SrmError as error:
        log(f"ERROR: {error}")
        return 1

    log("Checking the served certificate")
    if wait_for_served(config, local):
        log("SUCCESS: router serves the new certificate and it is trusted for DOMAIN")
        return 0
    log("ERROR: router does not serve the imported certificate")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Renew a Let's Encrypt certificate via Spaceship DNS-01 and deploy it to a Synology SRM router.",
    )
    parser.add_argument("--run", action="store_true", help="Apply changes (DNS records, issuance, router import)")
    parser.add_argument(
        "--allow-untrusted-router",
        action="store_true",
        help="Skip router TLS verification for this run only (bootstrap import over a self-signed certificate)",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"Config file (default: {DEFAULT_CONFIG})")
    subparsers = parser.add_subparsers(dest="command", metavar="{hook-auth,hook-cleanup}")
    subparsers.add_parser("hook-auth", help="certbot manual auth hook (internal)")
    subparsers.add_parser("hook-cleanup", help="certbot manual cleanup hook (internal)")
    args = parser.parse_args()

    config_path = args.config.expanduser().resolve()
    config = load_config(config_path)

    if args.command == "hook-auth":
        return hook_auth(config)
    if args.command == "hook-cleanup":
        return hook_cleanup(config)

    if not args.run:
        log(DRY_RUN_NOTICE)
    if args.allow_untrusted_router:
        log("WARNING: router TLS verification disabled for this run")
    status = run(config, config_path, args.run, args.allow_untrusted_router)
    if not args.run:
        log(DRY_RUN_NOTICE)
    return status


if __name__ == "__main__":
    sys.exit(main())
