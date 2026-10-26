import time

from lamp.web.auth import SessionSigner


def test_signer_roundtrip(tmp_path):
    s = SessionSigner(tmp_path / "secret.key", "pw")
    assert s.verify(s.issue())


def test_signer_rejects_tampered_and_other_password(tmp_path):
    s = SessionSigner(tmp_path / "secret.key", "pw")
    token = s.issue()
    assert not s.verify(token[:-1] + ("0" if token[-1] != "0" else "1"))
    assert not s.verify("garbage")
    assert not SessionSigner(tmp_path / "secret.key", "new-pw").verify(token)


def test_signer_expires(tmp_path):
    s = SessionSigner(tmp_path / "secret.key", "pw")
    old = s.issue(now=time.time() - 91 * 86400)
    assert not s.verify(old)


def test_check_password(tmp_path):
    s = SessionSigner(tmp_path / "secret.key", "pw")
    assert s.check_password("pw") and not s.check_password("nope")
