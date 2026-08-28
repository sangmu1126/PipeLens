import hashlib
import hmac


class InvalidSignatureError(ValueError):
    pass


def verify_github_signature(body: bytes, signature: str | None, secret: str) -> None:
    if not signature or not signature.startswith("sha256="):
        raise InvalidSignatureError("missing or malformed X-Hub-Signature-256 header")

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignatureError("webhook signature does not match")
