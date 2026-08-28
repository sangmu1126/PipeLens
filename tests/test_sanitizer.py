from pipelens.sanitizer import sanitize_log


def test_sanitize_log_removes_noise_and_secrets() -> None:
    raw = (
        "2026-08-28T01:02:03.000Z \x1b[31mERROR\x1b[0m\n"
        "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n"
        "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456\n"
        "contact=user@example.com"
    )

    sanitized, counts = sanitize_log(raw)

    assert sanitized.startswith("ERROR")
    assert "AKIAABCDEFGHIJKLMNOP" not in sanitized
    assert "ghp_" not in sanitized
    assert "user@example.com" not in sanitized
    assert counts == {"github_token": 1, "aws_access_key": 1, "authorization": 1, "email": 1}


def test_secret_assignment_keeps_variable_name() -> None:
    sanitized, counts = sanitize_log("DATABASE_PASSWORD=hunter2")

    assert sanitized == "DATABASE_PASSWORD=[REDACTED]"
    assert counts == {"secret_assignment": 1}
