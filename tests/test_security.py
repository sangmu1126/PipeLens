import hashlib
import hmac

import pytest

from pipelens.security import InvalidSignatureError, verify_github_signature


def test_verify_github_signature() -> None:
    body = b'{"action":"completed"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    verify_github_signature(body, signature, "secret")


def test_verify_github_signature_rejects_invalid_value() -> None:
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"payload", "sha256=bad", "secret")
