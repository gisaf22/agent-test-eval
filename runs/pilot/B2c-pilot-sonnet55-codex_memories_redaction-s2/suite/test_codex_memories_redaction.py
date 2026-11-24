# tests/test_codex_memories_redaction.py
import pytest

from codex_memories_redaction import (
    RedactionPolicy,
    redact_text,
    redact_value,
)


def test_policy_validation():
    with pytest.raises(ValueError):
        RedactionPolicy(replacement_prefix="")
    with pytest.raises(ValueError):
        RedactionPolicy(replacement_suffix="")
    with pytest.raises(ValueError):
        RedactionPolicy(additional_sensitive_keys=("",))
    with pytest.raises(ValueError):
        RedactionPolicy(additional_sensitive_keys=("a\x00b",))


def test_policy_is_frozen():
    with pytest.raises(Exception):
        RedactionPolicy().enabled = False


def test_empty_and_disabled():
    assert redact_text("") == ""
    p = RedactionPolicy(enabled=False)
    s = "password=hunter2"
    assert redact_text(s, p) == s


def test_private_key_block():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nb"
    out = redact_text(text)
    assert out == "a\n[REDACTED:private_key]\nb"
    out = redact_text("-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----")
    assert out == "[REDACTED:private_key]"


def test_cookie_header():
    out = redact_text("Set-Cookie: sid=abc123; Path=/\nother")
    assert out == "Set-Cookie: [REDACTED:cookie]\nother"
    assert redact_text("Cookie: a=b") == "Cookie: [REDACTED:cookie]"


def test_environment_secret():
    out = redact_text("export MY_API_KEY=\"abcdef\"")
    assert "abcdef" not in out
    assert "[REDACTED:environment_secret]" in out
    assert out.startswith('export MY_API_KEY="')


def test_authorization_header():
    out = redact_text("Authorization: Bearer abc.def")
    assert out == "Authorization: Bearer [REDACTED:authorization]"
    out = redact_text("Proxy-Authorization: Basic dXNlcjpwdw==")
    assert "dXNlcjpwdw" not in out


def test_url_credentials():
    out = redact_text("see https://user:pw123@example.com/path")
    assert out == "see https://[REDACTED:url_credentials]@example.com/path"
    assert redact_text("https://example.com/a") == "https://example.com/a"


def test_named_secret():
    out = redact_text("password=hunter2 next")
    assert out == "password=[REDACTED:named_secret] next"
    out = redact_text('{"api_key": "abc123"}')
    assert "abc123" not in out
    assert "[REDACTED:named_secret]" in out


def test_query_secret():
    out = redact_text("http://x.com/?a=1&token=abc123&b=2")
    assert "abc123" not in out
    assert "&b=2" in out
    assert "a=1" in out


def test_jwt():
    jwt = "eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeK"
    assert redact_text("t " + jwt) == "t [REDACTED:jwt]"


def test_openai_token():
    t = "sk-proj-" + "A" * 24
    assert redact_text("k " + t) == "k [REDACTED:openai_token]"


def test_github_tokens():
    assert redact_text("ghp_" + "a" * 36) == "[REDACTED:github_token]"
    assert redact_text("github_pat_" + "a" * 40) == "[REDACTED:github_token]"


def test_slack_token():
    assert redact_text("xoxb-" + "1" * 24) == "[REDACTED:slack_token]"


def test_aws_key():
    assert redact_text("AKIA" + "A" * 16) == "[REDACTED:aws_access_key]"
    assert redact_text("ASIA" + "B" * 12) == "[REDACTED:aws_access_key]"


def test_google_key():
    assert redact_text("AIza" + "a" * 35) == "[REDACTED:google_api_key]"


def test_stripe_key():
    assert redact_text("sk_live_" + "a" * 24) == "[REDACTED:stripe_secret_key]"
    assert redact_text("rk_test_" + "a" * 24) == "[REDACTED:stripe_secret_key]"


def test_npm_pypi():
    assert redact_text("npm_" + "a" * 36) == "[REDACTED:npm_token]"
    assert redact_text("pypi-" + "a" * 40) == "[REDACTED:pypi_token]"


def test_bearer_token():
    out = redact_text("use bearer " + "a" * 30)
    assert out == "use bearer [REDACTED:bearer_token]"


def test_benign_text_unchanged():
    for s in [
        "just prose about a password policy",
        "sha256 " + "a" * 64,
        "hello world",
        "token budget is large",
    ]:
        assert redact_text(s) == s


def test_custom_markers():
    p = RedactionPolicy(replacement_prefix="<", replacement_suffix=">")
    assert redact_text("password=abc", p) == "password=<named_secret>"


def test_value_sensitive_keys():
    v = {"password": "x", "user": "bob", "Api-Key": "k", "accessToken": "t"}
    out = redact_value(v)
    assert out["password"] == "[REDACTED:password]"
    assert out["user"] == "bob"
    assert out["Api-Key"] == "[REDACTED:api_key]"
    assert out["accessToken"] == "[REDACTED:access_token]"


def test_value_empty_sensitive_kept():
    out = redact_value({"password": "", "token": None})
    assert out == {"password": "", "token": None}


def test_value_nested_and_no_mutation():
    v = {"a": [{"secret": "s"}, ("password=abc",)], "n": 1}
    out = redact_value(v)
    assert out["a"][0] == {"secret": "[REDACTED:secret]"}
    assert out["a"][1] == ("password=[REDACTED:named_secret]",)
    assert isinstance(out["a"][1], tuple)
    assert out["n"] == 1
    assert v["a"][0] == {"secret": "s"}
    assert v["a"][1] == ("password=abc",)


def test_value_bytes_and_scalars_passthrough():
    assert redact_value(b"password=abc") == b"password=abc"
    assert redact_value(5) == 5
    assert redact_value(None) is None


def test_additional_keys():
    p = RedactionPolicy(additional_sensitive_keys=("MyField",))
    out = redact_value({"my_field": "v", "myField": "v"}, p)
    assert out == {"my_field": "[REDACTED:my_field]", "myField": "[REDACTED:my_field]"}


def test_value_disabled_copies():
    p = RedactionPolicy(enabled=False)
    v = {"password": "x", "l": [1, {"a": "b"}], "t": (1,)}
    out = redact_value(v, p)
    assert out == v
    assert out is not v
    assert out["l"] is not v["l"]
    assert out["l"][1] is not v["l"][1]
    assert isinstance(out["t"], tuple)
