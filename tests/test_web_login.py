from __future__ import annotations

from src.web_login import extract_login_url


def test_extract_login_url_success() -> None:
    text = (
        '--app="https://nas.nekous.cn:7005/'
        'launcher-login.html?port=50533&state=abc123"'
    )
    info = extract_login_url(text)
    assert info is not None
    assert info.port == "50533"
    assert info.state == "abc123"


def test_extract_login_url_missing_params() -> None:
    text = "https://nas.nekous.cn:7005/launcher-login.html"
    assert extract_login_url(text) is None
