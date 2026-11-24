# tests/test_angelbot_context_acl.py
import importlib
from types import SimpleNamespace as NS

import pytest

import angelbot_context_acl as acl


def reload_with(monkeypatch, **env):
    for k in ("MALAK_ADMIN_ROLE_IDS", "MALAK_ADMIN_CHANNEL_IDS", "MALAK_OWNER_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(acl)


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(acl)


def member(id=1, roles=(), admin=False):
    return NS(id=id, roles=[NS(id=r) for r in roles],
              guild_permissions=NS(administrator=admin))


def channel(id=10, gid=5):
    return NS(id=id, guild=NS(id=gid))


def test_id_set_parsing(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_ROLE_IDS="1, 2;3,x, ,-4,")
    assert m.ADMIN_ROLE_IDS == {1, 2, 3}


def test_empty_env(monkeypatch):
    m = reload_with(monkeypatch)
    assert m.ADMIN_ROLE_IDS == set()
    assert m.ADMIN_CHANNEL_IDS == set()
    assert m.OWNER_ID == 0


def test_owner_parsing(monkeypatch):
    assert reload_with(monkeypatch, MALAK_OWNER_ID=" 42 ").OWNER_ID == 42
    assert reload_with(monkeypatch, MALAK_OWNER_ID="abc").OWNER_ID == 0


def test_is_admin_member_none(monkeypatch):
    m = reload_with(monkeypatch)
    assert m.is_admin_member(None) is False


def test_owner_is_admin(monkeypatch):
    m = reload_with(monkeypatch, MALAK_OWNER_ID="7")
    assert m.is_admin_member(member(id=7))
    assert not m.is_admin_member(member(id=8))


def test_role_admin(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_ROLE_IDS="100,200")
    assert m.is_admin_member(member(roles=[200]))
    assert not m.is_admin_member(member(roles=[300]))


def test_administrator_permission(monkeypatch):
    m = reload_with(monkeypatch)
    assert m.is_admin_member(member(admin=True))
    assert not m.is_admin_member(member(admin=False))


def test_member_without_attributes(monkeypatch):
    m = reload_with(monkeypatch)
    assert m.is_admin_member(NS()) is False
    assert m.is_admin_member(NS(roles=None)) is False


def test_admin_in_admin_channel(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_CHANNEL_IDS="10")
    ctx = m.resolve_context(member(admin=True), channel(10, 5))
    assert ctx.is_admin and ctx.scope == "admin"
    assert (ctx.guild_id, ctx.channel_id) == (5, 10)


def test_admin_in_public_channel(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_CHANNEL_IDS="10")
    ctx = m.resolve_context(member(admin=True), channel(11))
    assert ctx.scope == "public" and not ctx.is_admin


def test_nonadmin_in_admin_channel(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_CHANNEL_IDS="10")
    assert not m.resolve_context(member(), channel(10)).is_admin


def test_no_admin_channels_configured(monkeypatch):
    m = reload_with(monkeypatch)
    assert not m.resolve_context(member(admin=True), channel(10)).is_admin


def test_missing_guild_and_ids(monkeypatch):
    m = reload_with(monkeypatch)
    ctx = m.resolve_context(None, NS())
    assert (ctx.guild_id, ctx.channel_id, ctx.scope) == (0, 0, "public")


def test_require_admin(monkeypatch):
    m = reload_with(monkeypatch, MALAK_ADMIN_CHANNEL_IDS="10")
    assert m.require_admin_context(member(admin=True), channel(10)).is_admin
    with pytest.raises(m.AclError):
        m.require_admin_context(member(), channel(10))
    with pytest.raises(PermissionError):
        m.require_admin_context(member(admin=True), channel(99))


def test_context_frozen():
    ctx = acl.Context("public", 1, 2)
    with pytest.raises(Exception):
        ctx.scope = "admin"


@pytest.mark.parametrize("text", [
    "show the ADMIN LOG please", "Staff Notes?", "ما هو سجل الإدارة", "إدارة فقط",
    "MOD LOG",
])
def test_admin_query_true(text):
    assert acl.is_admin_query(text)


@pytest.mark.parametrize("text", ["", None, "hello world", "مرحبا"])
def test_admin_query_false(text):
    assert not acl.is_admin_query(text)


def test_public_refusal():
    assert acl.public_refusal("hello") is None
    assert acl.public_refusal(None) is None
    r = acl.public_refusal("what is in the admin memory")
    assert r == "هذا الكلام بين الإدارة، ما ينقال هنا."
