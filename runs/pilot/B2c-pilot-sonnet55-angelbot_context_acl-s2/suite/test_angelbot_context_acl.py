# tests/test_angelbot_context_acl.py
import types
import pytest

import angelbot_context_acl as acl


def member(id=1, roles=(), admin=False):
    return types.SimpleNamespace(
        id=id,
        roles=[types.SimpleNamespace(id=r) for r in roles],
        guild_permissions=types.SimpleNamespace(administrator=admin),
    )


def channel(cid=100, gid=5):
    return types.SimpleNamespace(id=cid, guild=types.SimpleNamespace(id=gid))


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(acl, "ADMIN_ROLE_IDS", {10, 11})
    monkeypatch.setattr(acl, "ADMIN_CHANNEL_IDS", {100})
    monkeypatch.setattr(acl, "OWNER_ID", 999)


# ---- _id_set ----
def test_id_set_parsing(monkeypatch):
    monkeypatch.setenv("X_IDS", "1, 2;3,abc,,-4, 5 ")
    assert acl._id_set("X_IDS") == {1, 2, 3, 5}


def test_id_set_missing(monkeypatch):
    monkeypatch.delenv("X_IDS", raising=False)
    assert acl._id_set("X_IDS") == set()


# ---- is_admin_member ----
def test_none_member(cfg):
    assert acl.is_admin_member(None) is False


def test_owner(cfg):
    assert acl.is_admin_member(member(id=999)) is True


def test_admin_role(cfg):
    assert acl.is_admin_member(member(roles=[3, 11])) is True


def test_other_role_not_admin(cfg):
    assert acl.is_admin_member(member(roles=[3, 4])) is False


def test_administrator_permission(cfg):
    assert acl.is_admin_member(member(admin=True)) is True


def test_no_permissions_attr(cfg):
    m = types.SimpleNamespace(id=1, roles=None)
    assert acl.is_admin_member(m) is False


def test_owner_unset_does_not_match_zero(monkeypatch):
    monkeypatch.setattr(acl, "OWNER_ID", 0)
    monkeypatch.setattr(acl, "ADMIN_ROLE_IDS", set())
    m = types.SimpleNamespace(roles=[])
    assert acl.is_admin_member(m) is False


def test_empty_role_config_ignores_roles(monkeypatch):
    monkeypatch.setattr(acl, "OWNER_ID", 0)
    monkeypatch.setattr(acl, "ADMIN_ROLE_IDS", set())
    assert acl.is_admin_member(member(roles=[0, 10])) is False


# ---- resolve_context ----
def test_admin_in_admin_channel(cfg):
    ctx = acl.resolve_context(member(roles=[10]), channel())
    assert ctx.is_admin and ctx.scope == "admin"
    assert (ctx.guild_id, ctx.channel_id) == (5, 100)


def test_admin_in_public_channel(cfg):
    ctx = acl.resolve_context(member(roles=[10]), channel(cid=200))
    assert ctx.scope == "public" and not ctx.is_admin


def test_nonadmin_in_admin_channel(cfg):
    assert acl.resolve_context(member(), channel()).scope == "public"


def test_no_admin_channels_configured(monkeypatch, cfg):
    monkeypatch.setattr(acl, "ADMIN_CHANNEL_IDS", set())
    assert acl.resolve_context(member(id=999), channel()).scope == "public"


def test_channel_without_guild(cfg):
    ctx = acl.resolve_context(member(id=999), types.SimpleNamespace(id=100))
    assert ctx.guild_id == 0 and ctx.is_admin


def test_none_member_public(cfg):
    assert acl.resolve_context(None, channel()).scope == "public"


def test_context_frozen():
    c = acl.Context("public", 1, 2)
    with pytest.raises(Exception):
        c.scope = "admin"


# ---- require_admin_context ----
def test_require_ok(cfg):
    assert acl.require_admin_context(member(admin=True), channel()).is_admin


def test_require_refuses_wrong_channel(cfg):
    with pytest.raises(acl.AclError):
        acl.require_admin_context(member(admin=True), channel(cid=1))


def test_require_refuses_wrong_member(cfg):
    with pytest.raises(PermissionError):
        acl.require_admin_context(member(), channel())


# ---- queries ----
@pytest.mark.parametrize("q", [
    "show ADMIN LOG please", "what is in Staff Notes", "سجل الإدارة لو سمحت",
    "هذا إدارة فقط", "Mod Log?", "admin memory",
])
def test_admin_query_true(q):
    assert acl.is_admin_query(q) is True


@pytest.mark.parametrize("q", ["", None, "hello world", "what's the weather"])
def test_admin_query_false(q):
    assert acl.is_admin_query(q) is False


def test_public_refusal():
    r = acl.public_refusal("give me the admin log")
    assert r == "هذا الكلام بين الإدارة، ما ينقال هنا."


def test_public_refusal_none():
    assert acl.public_refusal("hi there") is None
    assert acl.public_refusal(None) is None
