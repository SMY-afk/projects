from scripts.check_no_secrets import find_violations


def test_secret_scan_rejects_backend_secrets_exposed_as_vite_variables() -> None:
    content = (
        "VITE_TIKTOK_APP_SECRET=\n"
        "VITE_TOKEN_ENCRYPTION_KEY=\n"
        "VITE_POSTGRES_PASSWORD=\n"
        "VITE_DATABASE_URL=\n"
        "VITE_JWT_SECRET="
    )

    violations = find_violations("erp-web/.env.example", content)

    assert len(violations) == 5
    assert all("server-only secret" in violation for violation in violations)


def test_secret_scan_allows_placeholders_in_backend_env_examples() -> None:
    content = (
        "POSTGRES_PASSWORD=<database-password>\n"
        "AUTH_CAPTCHA_HMAC_SECRET=<random-server-secret>\n"
        "TIKTOK_APP_SECRET=<tiktok-app-secret>\n"
        "TIKTOK_TOKEN_ENCRYPTION_KEY=<token-encryption-key>"
    )

    assert find_violations(".env.example", content) == []


def test_secret_scan_allows_empty_structured_secret_maps() -> None:
    assert find_violations(
        ".env.example", "LOGISTICS_WEBHOOK_SIGNING_SECRETS={}"
    ) == []


def test_secret_scan_does_not_treat_python_variables_as_environment_values() -> None:
    content = (
        "password = generate_admin_password()\nvalidate_admin_password(password)\n"
    )

    assert find_violations("scripts/bootstrap_admin.py", content) == []


def test_secret_scan_allows_non_secret_token_and_password_metadata() -> None:
    content = (
        'TOKEN_PATTERNS = (re.compile("example"),)\n'
        'PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"\n'
        "PASSWORD_HASH_ITERATIONS = 600_000\n"
        "TIKTOK_VIDEO_NEXT_PAGE_TOKEN_PATH=next_page_token"
    )

    assert find_violations("config.example", content) == []


def test_secret_scan_still_rejects_plaintext_secret_assignments() -> None:
    assert find_violations("settings.py", 'API_KEY = "not-a-placeholder"') == [
        "settings.py:1: detected a non-placeholder secret value"
    ]
