# tests/test_angelbot_context_acl.py
import importlib
from types import SimpleNamespace as NS

import pytest

import angelbot_context_acl as acl


@pytest.fixture
def cfg(monkeypatch):
    """Set module-level config directly (deterministic)."""
    def _set(roles=(), channels=(), owner=0):
        monkeypatch.setattr(acl, "ADMIN_ROLE_IDS", set(roles))
        monkeypatch.setattr(acl, "ADMIN_CHANNEL_IDS", set(channels))
        monkeypatch.setattr(acl, "OWNER_ID", owner)
    return _set


def member(mid=1, roles=(), admin=False):
    return NS(id=mid, roles=[NS(id=r) for r in roles],
              guild_permissions=NS(administrator=admin))


def channel(cid=10, gid=5):
    return NS(id=cid, guild=NS(id=gid))


# ---- env parsing ----
def test_id_set_parsing(monkeypatch):
    monkeypatch.setenv("X_IDS", "1, 2;3,abc,,-4, 5 ")
    assert acl._id_set("X_IDS") == {1, 2, 3, 5}


def test_id_set_missing(monkeypatch):
    monkeypatch.delenv("X_IDS", raising=False)
    assert acl._id_set("X_IDS") == set()


def test_module_env_loading(monkeypatch):
    monkeypatch.setenv("MALAK_ADMIN_ROLE_IDS", "7;8")
    monkeypatch.setenv("MALAK_ADMIN_CHANNEL_IDS", "9")
    monkeypatch.setenv("MALAK_OWNER_ID", " 42 ")
    try:
        m = importlib.reload(acl)
        assert m.ADMIN_ROLE_IDS == {7, 8}
        assert m.ADMIN_CHANNEL_IDS == {9}
        assert m.OWNER_ID == 42
        monkeypatch.setenv("MALAK_OWNER_ID", "notnum")
        m = importlib.reload(acl)
        assert m.OWNER_ID == 0
    finally:
        monkeypatch.undo()
        importlib.reload(acl)


# ---- is_admin_member ----
def test_none_member(cfg):
    cfg()
    assert acl.is_admin_member(None) is False


def test_owner(cfg):
    cfg(owner=99)
    assert acl.is_admin_member(member(mid=99)) is True
    assert acl.is_admin_member(member(mid=98)) is False


def test_owner_zero_does_not_match_missing_id(cfg):
    cfg(owner=0)
    assert acl.is_admin_member(NS()) is False


def test_admin_role(cfg):
    cfg(roles={100})
    assert acl.is_admin_member(member(roles=[100, 3])) is True
    assert acl.is_admin_member(member(roles=[3])) is False


def test_administrator_permission(cfg):
    cfg()
    assert acl.is_admin_member(member(admin=True)) is True
    assert acl.is_admin_member(member(admin=False)) is False


def test_no_perms_or_roles_attrs(cfg):
    cfg(roles={1})
    assert acl.is_admin_member(NS(id=5)) is False
    assert acl.is_admin_member(NS(id=5, roles=None)) is False


# ---- resolve_context ----
def test_admin_in_admin_channel(cfg):
    cfg(roles={100}, channels={10})
    ctx = acl.resolve_context(member(roles=[100]), channel(10, 5))
    assert ctx == acl.Context("admin", 5, 10)
    assert ctx.is_admin


def test_admin_in_public_channel(cfg):
    cfg(roles={100}, channels={10})
    ctx = acl.resolve_context(member(roles=[100]), channel(11))
    assert ctx.scope == "public" and not ctx.is_admin


def test_non_admin_in_admin_channel(cfg):
    cfg(roles={100}, channels={10})
    assert not acl.resolve_context(member(roles=[1]), channel(10)).is_admin


def test_no_admin_channels_configured(cfg):
    cfg(roles={100}, channels=())
    assert not acl.resolve_context(member(roles=[100]), channel(10)).is_admin


def test_dm_channel_without_guild(cfg):
    cfg(channels={10})
    ctx = acl.resolve_context(member(admin=True), NS(id=10))
    assert ctx.guild_id == 0 and ctx.is_admin


def test_missing_ids_default_zero(cfg):
    cfg()
    ctx = acl.resolve_context(None, NS())
    assert ctx == acl.Context("public", 0, 0)


def test_context_frozen():
    c = acl.Context("public", 1, 2)
    with pytest.raises(Exception):
        c.scope = "admin"


# ---- require_admin_context ----
def test_require_ok(cfg):
    cfg(channels={10})
    assert acl.require_admin_context(member(admin=True), channel(10)).is_admin


def test_require_refuses(cfg):
    cfg(channels={10})
    with pytest.raises(acl.AclError):
        acl.require_admin_context(member(admin=False), channel(10))
    with pytest.raises(PermissionError):
        acl.require_admin_context(member(admin=True), channel(11))
    with pytest.raises(acl.AclError):
        acl.require_admin_context(None, channel(10))


# ---- queries ----
@pytest.mark.parametrize("q", [
    "show me the ADMIN LOG", "what is in Admin Memory?", "mod log please",
    "Staff Notes", "ايش قرارات الإدارة أمس", "سجل الإدارة", "إدارة فقط",
])
def test_admin_query_true(q):
    assert acl.is_admin_query(q) is True


@pytest.mark.parametrize("q", ["hello", "", None, "ما الطقس اليوم"])
def test_admin_query_false(q):
    assert acl.is_admin_query(q) is False


def test_public_refusal():
    assert acl.public_refusal("hello") is None
    assert acl.public_refusal("") is None
    assert acl.public_refusal(None) is None
    r = acl.public_refusal("admin log")
    assert r == "هذا الكلام بين الإدارة، ما ينقال هنا."
