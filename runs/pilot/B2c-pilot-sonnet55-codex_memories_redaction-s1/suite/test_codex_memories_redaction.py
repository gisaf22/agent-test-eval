# tests/test_codex_memories_redaction.py
import dataclasses

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


def test_policy_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        RedactionPolicy().enabled = False


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


# ---------- redact_text ----------

def test_empty_and_disabled():
    assert redact_text("") == ""
    text = "password=hunter2"
    assert redact_text(text, RedactionPolicy(enabled=False)) == text


def test_private_key_block():
    text = "before\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nafter"
    out = redact_text(text)
    assert out == "before\n[REDACTED:private_key]\nafter"


def test_private_key_plain_header():
    text = "-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----"
    assert redact_text(text) == "[REDACTED:private_key]"


def test_cookie_headers():
    out = redact_text("Cookie: session=abc123; other=zzz")
    assert out == "Cookie: [REDACTED:cookie]"
    out = redact_text("GET /\nSet-Cookie: id=999; HttpOnly\nnext line")
    assert out == "GET /\nSet-Cookie: [REDACTED:cookie]\nnext line"


def test_environment_secret():
    out = redact_text("export API_TOKEN=abc123xyz")
    assert out == "export API_TOKEN=[REDACTED:environment_secret]"
    out = redact_text('DB_PASSWORD="s3cret"')
    assert "s3cret" not in out
    assert "[REDACTED:environment_secret]" in out


def test_authorization_header():
    out = redact_text("Authorization: Bearer abcdef123")
    assert out == "Authorization: Bearer [REDACTED:authorization]"
    out = redact_text("Proxy-Authorization: Basic dXNlcjpwYXNz")
    assert out == "Proxy-Authorization: Basic [REDACTED:authorization]"


def test_url_credentials():
    out = redact_text("postgres://user:pass@host/db")
    assert out == "postgres://[REDACTED:url_credentials]@host/db"


def test_url_without_credentials_unchanged():
    text = "https://example.com/path:80/x"
    assert redact_text(text) == text


def test_named_secret_forms():
    assert redact_text("password=hunter2") == "password=[REDACTED:named_secret]"
    out = redact_text('{"api_key": "abcd1234"}')
    assert "abcd1234" not in out
    assert "[REDACTED:named_secret]" in out
    out = redact_text("client-secret: topsecretvalue")
    assert "topsecretvalue" not in out


def test_query_string_secret():
    out = redact_text("https://x.com/?token=abc123&x=1")
    assert "abc123" not in out
    assert "&x=1" in out


def test_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
    assert redact_text("x " + jwt + " y") == "x [REDACTED:jwt] y"


@pytest.mark.parametrize(
    "token,kind",
    [
        ("sk-" + "a" * 24, "openai_token"),
        ("sk-proj-" + "a" * 24, "openai_token"),
        ("ghp_" + "A" * 36, "github_token"),
        ("github_pat_" + "A" * 40, "github_token"),
        ("xoxb-" + "a1" * 12, "slack_token"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("AIza" + "a" * 35, "google_api_key"),
        ("sk_live_" + "a" * 24, "stripe_secret_key"),
        ("rk_test_" + "a" * 24, "stripe_secret_key"),
        ("npm_" + "a" * 36, "npm_token"),
        ("pypi-" + "a" * 40, "pypi_token"),
    ],
)
def test_known_token_formats(token, kind):
    assert redact_text(f"found {token} here") == f"found [REDACTED:{kind}] here"


def test_bearer_token():
    out = redact_text("use bearer " + "a" * 25)
    assert out == "use bearer [REDACTED:bearer_token]"


@pytest.mark.parametrize(
    "text",
    [
        "a" * 64,
        "sha256:" + "0123456789abcdef" * 4,
        "the password policy is strong",
        "sk-short",
        "plain prose about tokens and secrets",
    ],
)
def test_non_secrets_unchanged(text):
    assert redact_text(text) == text


def test_custom_markers():
    p = RedactionPolicy(replacement_prefix="<<", replacement_suffix=">>")
    assert redact_text("password=x", p) == "password=<<named_secret>>"


def test_multiple_secrets_in_one_string():
    out = redact_text("password=one and " + "ghp_" + "B" * 36)
    assert "one" not in out.replace("[REDACTED:named_secret]", "")
    assert "[REDACTED:github_token]" in out


# ---------- redact_value ----------

def test_sensitive_keys_redacted():
    out = redact_value({"password": "x", "user": "bob"})
    assert out == {"password": "[REDACTED:password]", "user": "bob"}


def test_key_normalization():
    out = redact_value({"apiKey": "v", "Api-Key": "v", "accessToken": "v", "Authorization": "v"})
    assert out == {
        "apiKey": "[REDACTED:api_key]",
        "Api-Key": "[REDACTED:api_key]",
        "accessToken": "[REDACTED:access_token]",
        "Authorization": "[REDACTED:authorization]",
    }


def test_empty_sensitive_values_kept():
    assert redact_value({"token": None, "password": ""}) == {"token": None, "password": ""}


def test_nested_structures_and_types():
    data = {
        "list": [{"secret": "a"}, "password=zzz"],
        "tup": ({"token": "b"}, 5),
        "n": 3,
        "f": 1.5,
        "b": b"password=zzz",
        "none": None,
    }
    out = redact_value(data)
    assert out["list"][0] == {"secret": "[REDACTED:secret]"}
    assert out["list"][1] == "password=[REDACTED:named_secret]"
    assert isinstance(out["list"], list)
    assert isinstance(out["tup"], tuple)
    assert out["tup"] == ({"token": "[REDACTED:token]"}, 5)
    assert out["n"] == 3 and out["f"] == 1.5 and out["none"] is None
    assert out["b"] == b"password=zzz"


def test_does_not_mutate_input():
    data = {"password": "x", "items": ["password=y"]}
    snapshot = {"password": "x", "items": ["password=y"]}
    out = redact_value(data)
    assert data == snapshot
    assert out is not data
    assert out["items"] is not data["items"]


def test_string_top_level():
    assert redact_value("password=abc") == "password=[REDACTED:named_secret]"


def test_additional_sensitive_keys():
    p = RedactionPolicy(additional_sensitive_keys=("MyKey",))
    out = redact_value({"myKey": "v", "other": "v"}, p)
    assert out == {"myKey": "[REDACTED:my_key]", "other": "v"}


def test_non_string_dict_keys_preserved():
    assert redact_value({1: "a", "password": "b"}) == {1: "a", "password": "[REDACTED:password]"}


def test_disabled_returns_copy_unredacted():
    p = RedactionPolicy(enabled=False)
    data = {"password": "x", "l": ["password=y"], "t": (1, 2)}
    out = redact_value(data, p)
    assert out == data
    assert out is not data
    assert out["l"] is not data["l"]
    assert isinstance(out["t"], tuple)


def test_custom_marker_in_value():
    p = RedactionPolicy(replacement_prefix="{", replacement_suffix="}")
    assert redact_value({"token": "abc"}, p) == {"token": "{token}"}
