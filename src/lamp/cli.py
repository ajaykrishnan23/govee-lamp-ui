"""Command line: `lamp serve|discover|certs|install-agent|uninstall-agent`."""
import argparse
import asyncio
import logging
import shutil
import socket
import subprocess
import sys

from pydantic import ValidationError

from . import config


def load_settings() -> config.Settings:
    """Settings, or a short readable exit (never echoing values: they include API keys)."""
    try:
        return config.get_settings()
    except ValidationError as e:
        lines = []
        for err in e.errors():
            name = str(err["loc"][0]).upper() if err["loc"] else "?"
            reason = "is missing" if err["type"] == "missing" else f"is invalid ({err['msg']})"
            lines.append(f"  {name} {reason}")
        sys.exit(f"Problem with settings in {config.ENV_FILE}:\n" + "\n".join(lines))


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packets sent; picks the outbound interface
        return s.getsockname()[0]
    finally:
        s.close()


def _hostname() -> str:
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    except OSError:
        name = ""
    return f"{name or socket.gethostname().split('.')[0]}.local"


def cmd_serve(_args) -> None:
    import uvicorn

    from .runtime import build_app

    s = load_settings()
    app, _ = build_app(s, keep_awake=True)
    cert, key = s.certs_dir / "lamp.pem", s.certs_dir / "lamp-key.pem"
    ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)} if cert.exists() and key.exists() else {}
    if not ssl:
        print("!! No certificates in certs/ - serving plain HTTP. The phone mic needs HTTPS: run `lamp certs`.",
              file=sys.stderr)
    print(f"Lamp at http{'s' if ssl else ''}://{_hostname()}:{s.port}  (or {_lan_ip()})")
    uvicorn.run(app, host=s.host, port=s.port, log_level="info", **ssl)


def cmd_discover(_args) -> None:
    from .govee.transport import discover

    bulbs = asyncio.run(discover(3))
    for b in bulbs:
        print(f"{b.sku}  {b.ip:<15}  {b.mac}")
    if not bulbs:
        print("No bulbs answered. Is LAN Control on in the Govee app, and is this Mac on the same Wi-Fi?")


def cmd_certs(_args) -> None:
    if not shutil.which("mkcert"):
        sys.exit("mkcert not found: brew install mkcert")
    s = load_settings()
    s.certs_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mkcert", "-install"], check=True)
    names = [_hostname(), _lan_ip(), "localhost", "127.0.0.1"]
    subprocess.run(["mkcert", "-cert-file", str(s.certs_dir / "lamp.pem"),
                    "-key-file", str(s.certs_dir / "lamp-key.pem"), *names], check=True)
    caroot = subprocess.run(["mkcert", "-CAROOT"], capture_output=True, text=True).stdout.strip()
    print(f"""
Certificates written for {', '.join(names)}.
To trust them on your iPhone (once):
  1. AirDrop {caroot}/rootCA.pem to the phone and tap Allow.
  2. Settings > General > VPN & Device Management > install the downloaded profile.
  3. Settings > General > About > Certificate Trust Settings > turn on full trust for the mkcert root.
Then open https://{names[0]}:{s.port} in Chrome.""")


def cmd_install_agent(_args) -> None:
    import os
    from pathlib import Path

    from .resilience import agent_path, agent_plist

    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv not found on PATH")
    repo = Path.cwd().resolve()
    if not (repo / "pyproject.toml").exists():
        sys.exit("run this from the project folder")
    (repo / "data").mkdir(exist_ok=True)
    path = agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True)  # replace any old copy
    path.write_bytes(agent_plist(repo, uv))
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print(f"Installed {path}. The lamp server now starts at login; logs in data/lamp.log")


def cmd_uninstall_agent(_args) -> None:
    import os

    from .resilience import agent_path

    path = agent_path()
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
    path.unlink(missing_ok=True)
    print("Removed the login agent.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="lamp", description="Control the Govee lamp.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help in [
        ("serve", cmd_serve, "run the web app"),
        ("discover", cmd_discover, "list bulbs on the LAN"),
        ("certs", cmd_certs, "make HTTPS certificates with mkcert"),
        ("install-agent", cmd_install_agent, "start the app at login"),
        ("uninstall-agent", cmd_uninstall_agent, "stop starting at login"),
    ]:
        sub.add_parser(name, help=help).set_defaults(fn=fn)
    args = p.parse_args()
    args.fn(args)
