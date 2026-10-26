"""Single-password login with an HMAC-signed session cookie."""
import hashlib
import hmac
import secrets
import time
from pathlib import Path

COOKIE = "lamp_session"
MAX_AGE_S = 90 * 86400


class SessionSigner:
    def __init__(self, secret_path: Path, password: str):
        if not secret_path.exists():
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_bytes(secrets.token_bytes(32))
            secret_path.chmod(0o600)
        # mixing in the password means changing it logs everyone out
        self._key = secret_path.read_bytes() + password.encode()
        self._password = password

    def _sig(self, issued: str) -> str:
        return hmac.new(self._key, issued.encode(), hashlib.sha256).hexdigest()

    def issue(self, now: float | None = None) -> str:
        issued = str(int(now if now is not None else time.time()))
        return f"{issued}.{self._sig(issued)}"

    def verify(self, token: str | None) -> bool:
        try:
            issued, sig = (token or "").split(".", 1)
            fresh = time.time() - int(issued) < MAX_AGE_S
        except ValueError:
            return False
        return fresh and hmac.compare_digest(sig, self._sig(issued))

    def check_password(self, password: str) -> bool:
        return hmac.compare_digest(password.encode(), self._password.encode())
