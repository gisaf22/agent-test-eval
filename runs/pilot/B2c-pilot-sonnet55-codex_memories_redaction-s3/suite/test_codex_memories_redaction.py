# tests/test_codex_memories_redaction.py
import pytest

from codex_memories_redaction import (
    RedactionPolicy,
    redact_text,
    redact_value,
)


# ---------- policy ----------

def test_policy_defaults():
    p = RedactionPolicy()
    assert p.enabled is True
    assert p.replacement_prefix == "[REDACTED:"
    assert p.replacement_suffix == "]"
    assert p.additional_sensitive_keys == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"replacement_prefix": ""},
        {"replacement_suffix": ""},
        {"additional_sensitive_keys": ("",)},
        {"additional_sensitive_keys": ("a\x00b",)},
    ],
)
def test_policy_validation(kwargs):
    with pytest.raises(ValueError):
        RedactionPolicy(**kwargs)


def test_policy_frozen():
    with pytest.raises(Exception):
        RedactionPolicy().enabled = False  # type: ignore[misc]


# ---------- redact_text ----------

def test_empty_and_disabled():
    assert redact_text("") == ""
    pol = RedactionPolicy(enabled=False)
    s = "password=hunter2"
    assert redact_text(s, pol) == s


def test_private_key_block():
    text = "before\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nafter"
    out = redact_text(text)
    assert out == "before\n[REDACTED:private_key]\nafter"


def test_plain_private_key_block():
    text = "-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----"
    assert redact_text(text) == "[REDACTED:private_key]"


def test_cookie_headers():
    assert redact_text("Cookie: session=abc; other=1") == "Cookie: [REDACTED:cookie]"
    assert redact_text("Set-Cookie: id=1; Path=/") == "Set-Cookie: [REDACTED:cookie]"


def test_environment_secret():
    assert (
        redact_text("MY_SECRET=hunter2") == "MY_SECRET=[REDACTED:environment_secret]"
    )
    assert (
        redact_text("export OPENAI_API_KEY=abc123")
        == "export OPENAI_API_KEY=[REDACTED:environment_secret]"
    )
    assert (
        redact_text('export DB_PASSWORD="pw"')
        == 'export DB_PASSWORD="[REDACTED:environment_secret]"'
    )


def test_authorization_header():
    assert (
        redact_text("Authorization: Bearer abc.def")
        == "Authorization: Bearer [REDACTED:authorization]"
    )
    assert (
        redact_text("Authorization: Basic dXNlcjpwYXNz")
        == "Authorization: Basic [REDACTED:authorization]"
    )
    assert (
        redact_text("Proxy-Authorization: Basic dXNlcjpwYXNz")
        == "Proxy-Authorization: Basic [REDACTED:authorization]"
    )


def test_url_credentials():
    out = redact_text("https://user:pass@example.com/x")
    assert out == "https://[REDACTED:url_credentials]@example.com/x"


def test_url_without_credentials_untouched():
    s = "https://example.com:8080/path"
    assert redact_text(s) == s


def test_named_secret_forms():
    assert redact_text("password=hunter2") == "password=[REDACTED:named_secret]"
    assert (
        redact_text('{"password": "hunter2"}')
        == '{"password": "[REDACTED:named_secret]"}'
    )
    assert redact_text("API-KEY: abc") == "API-KEY: [REDACTED:named_secret]"


def test_query_secret_removed():
    out = redact_text("https://x.com/?sig=1&token=abc123&a=1")
    assert "abc123" not in out
    assert "a=1" in out


def test_jwt():
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    )
    assert redact_text("see " + jwt + " ok") == "see [REDACTED:jwt] ok"


@pytest.mark.parametrize(
    "token,kind",
    [
        ("sk-" + "a" * 24, "openai_token"),
        ("sk-proj-" + "a" * 24, "openai_token"),
        ("ghp_" + "a" * 36, "github_token"),
        ("github_pat_" + "a" * 40, "github_token"),
        ("xoxb-" + "1" * 24, "slack_token"),
        ("AKIA" + "A" * 16, "aws_access_key"),
        ("ASIA" + "B" * 12, "aws_access_key"),
        ("AIza" + "a" * 35, "google_api_key"),
        ("sk_live_" + "a" * 24, "stripe_secret_key"),
        ("rk_test_" + "a" * 24, "stripe_secret_key"),
        ("npm_" + "a" * 36, "npm_token"),
        ("pypi-" + "a" * 40, "pypi_token"),
    ],
)
def test_known_token_formats(token, kind):
    out = redact_text("value " + token + " end")
    assert out == "value [REDACTED:%s] end" % kind


def test_bearer_token_in_prose():
    out = redact_text("use Bearer abcdefghijklmnopqrstuvwx now")
    assert out == "use Bearer [REDACTED:bearer_token] now"


def test_short_bearer_untouched():
    s = "use Bearer short now"
    assert redact_text(s) == s


def test_benign_text_untouched():
    for s in [
        "the password is stored securely",
        "sha256 " + "a1b2c3d4" * 8,
        "hello world",
    ]:
        assert redact_text(s) == s


def test_custom_markers():
    pol = RedactionPolicy(replacement_prefix="<<", replacement_suffix=">>")
    assert redact_text("password=x", pol) == "password=<<named_secret>>"


# ---------- redact_value ----------

def test_sensitive_keys_in_dict():
    out = redact_value({"password": "x", "user": "bob"})
    assert out == {"password": "[REDACTED:password]", "user": "bob"}


def test_key_normalization():
    out = redact_value({"accessToken": "a", "API-Key": "b", "apiKey": "c"})
    assert out == {
        "accessToken": "[REDACTED:access_token]",
        "API-Key": "[REDACTED:api_key]",
        "apiKey": "[REDACTED:api_key]",
    }


def test_empty_sensitive_values_kept():
    assert redact_value({"token": None, "password": ""}) == {"token": None, "password": ""}


def test_sensitive_key_with_container_value():
    assert redact_value({"credentials": {"a": 1}}) == {
        "credentials": "[REDACTED:credentials]"
    }


def test_nested_structures_and_types():
    data = {
        "items": [{"secret": "s"}, "password=abc"],
        "t": ("password=abc", 5),
        "n": 3,
        "b": b"password=abc",
        "f": 1.5,
        "none": None,
    }
    out = redact_value(data)
    assert out["items"] == [{"secret": "[REDACTED:secret]"}, "password=[REDACTED:named_secret]"]
    assert out["t"] == ("password=[REDACTED:named_secret]", 5)
    assert isinstance(out["t"], tuple)
    assert out["n"] == 3 and out["f"] == 1.5 and out["none"] is None
    assert out["b"] == b"password=abc"


def test_no_mutation():
    data = {"a": ["password=abc", {"token": "t"}], "b": ("x",)}
    snapshot = {"a": ["password=abc", {"token": "t"}], "b": ("x",)}
    out = redact_value(data)
    assert data == snapshot
    assert out is not data


def test_top_level_string_and_scalars():
    assert redact_value("password=x") == "password=[REDACTED:named_secret]"
    assert redact_value(7) == 7
    assert redact_value(None) is None


def test_non_string_keys_preserved():
    assert redact_value({1: "password=abc"}) == {1: "password=[REDACTED:named_secret]"}


def test_additional_sensitive_keys():
    pol = RedactionPolicy(additional_sensitive_keys=("MyKey",))
    out = redact_value({"myKey": "v", "other": "w"}, pol)
    assert out == {"myKey": "[REDACTED:my_key]", "other": "w"}


def test_custom_markers_in_value():
    pol = RedactionPolicy(replacement_prefix="{", replacement_suffix="}")
    assert redact_value({"token": "x"}, pol) == {"token": "{token}"}


def test_disabled_returns_copy_without_redaction():
    pol = RedactionPolicy(enabled=False)
    data = {"password": "x", "l": ["password=abc"], "t": ("a",)}
    out = redact_value(data, pol)
    assert out == data
    assert out is not data
    assert out["l"] is not data["l"]
    assert isinstance(out["t"], tuple)
