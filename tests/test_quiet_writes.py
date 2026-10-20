"""Plain writes and notes carry the context that keeps them quiet, and only that.

Clients ask for approval per tool. A write that needed `mail_notrack` used to
go through `execute`, which runs any method and is rightly confirmed every time,
so routine writes were confirmed like an `unlink`. `create`, `write` and
`message_post` now take a context, but only keys that quiet the chatter: a key
that changes what the call does is refused before anything reaches Odoo.
"""

import asyncio
import json

import pytest

import odoo_fast_mcp.tools.crud as crud
from odoo_fast_mcp.connection import OdooConnectionManager

WEB = "https://odoo.example.test"
QUIET = {"mail_create_nolog": True, "mail_auto_subscribe_no_notify": True}

# --- Parsing the context argument ---------------------------------------------


@pytest.mark.parametrize("context", [None, "", "{}"])
def test_no_context_means_none_sent(context):
    assert crud._quiet_context(context) is None


def test_every_quiet_key_is_accepted():
    every = dict.fromkeys(crud.QUIET_CONTEXT_KEYS, True)
    assert crud._quiet_context(json.dumps(every)) == every


@pytest.mark.parametrize(
    "key",
    ["default_user_id", "active_test", "allowed_company_ids", "force_company", "install_mode"],
)
def test_a_key_that_changes_the_call_is_refused_and_points_to_execute(key):
    with pytest.raises(ValueError, match=key) as caught:
        crud._quiet_context(json.dumps({"mail_notrack": True, key: 1}))
    assert "`execute`" in str(caught.value)


def test_context_must_be_an_object():
    with pytest.raises(TypeError):
        crud._quiet_context('["mail_notrack"]')


# --- What the manager sends ---------------------------------------------------


class _Model:
    """odoorpc model stand-in: records the context a create would carry."""

    def __init__(self, calls, context):
        self._calls = calls
        self._context = context

    def with_context(self, **kwargs):
        return _Model(self._calls, {**self._context, **kwargs})

    def create(self, values):
        self._calls.append(("create", values, self._context))
        return 42


class _RecordingOdoo:
    USER_CONTEXT = {"lang": "en_US", "tz": "Asia/Manila", "uid": 7}

    def __init__(self):
        self.calls = []
        self.env = {"project.task": _Model(self.calls, self.USER_CONTEXT)}

    def execute(self, model, method, *args):
        self.calls.append(("execute", model, method, args))
        return True

    def execute_kw(self, model, method, args, kwargs):
        self.calls.append(("execute_kw", model, method, args, kwargs))
        return 99


@pytest.fixture
def manager():
    manager = OdooConnectionManager()
    manager._odoo = _RecordingOdoo()
    manager._connected = True
    return manager


def test_write_without_context_is_the_call_it_always_was(manager):
    manager.write("project.task", [5], {"name": "N"})
    assert manager._odoo.calls == [("execute", "project.task", "write", ([5], {"name": "N"}))]


def test_write_with_context_sends_it_as_a_keyword(manager):
    manager.write("project.task", [5], {"stage_id": 43}, context={"mail_notrack": True})
    assert manager._odoo.calls == [
        ("execute_kw", "project.task", "write", [[5], {"stage_id": 43}],
         {"context": {"mail_notrack": True}}),
    ]


def test_create_merges_the_context_over_the_user_context(manager):
    # Replacing it would drop the user's lang, and translatable fields would be
    # written in the wrong language.
    manager.create("project.task", {"name": "N"}, context=QUIET)
    ((_, _, sent),) = manager._odoo.calls
    assert sent == {**_RecordingOdoo.USER_CONTEXT, **QUIET}


def test_a_note_is_what_the_log_note_button_posts(manager):
    manager.message_post("project.task", 5, "<p>Done</p>", [12, 13], {"mail_create_nosubscribe": True})
    assert manager._odoo.calls == [
        ("execute_kw", "project.task", "message_post", [[5]], {
            "body": "<p>Done</p>",
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_note",
            "attachment_ids": [12, 13],
            "context": {"mail_create_nosubscribe": True},
        }),
    ]


def test_a_note_never_names_its_author_or_anyone_to_notify(manager):
    manager.message_post("project.task", 5, "<p>Done</p>")
    ((*_, kwargs),) = manager._odoo.calls
    assert not {"author_id", "email_from", "partner_ids"} & set(kwargs)


# --- The tools ----------------------------------------------------------------


class _FakeManager:
    web_url = WEB

    def __init__(self):
        self.calls = []

    def create(self, model, values, context=None):
        self.calls.append(("create", context))
        return 42

    def write(self, model, ids, values, context=None):
        self.calls.append(("write", context))
        return True

    def message_post(self, model, res_id, body, attachment_ids=None, context=None):
        self.calls.append(("message_post", attachment_ids, context))
        return 99


@pytest.fixture
def fake_manager(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(crud, "odoo_manager", fake)
    return fake


def test_write_passes_a_quiet_context_through(fake_manager):
    asyncio.run(crud.write(
        model="project.task", ids="[5]", values='{"stage_id": 43}', context=json.dumps(QUIET),
    ))
    assert fake_manager.calls == [("write", QUIET)]


def test_create_passes_a_quiet_context_through(fake_manager):
    asyncio.run(crud.create(model="project.task", values='{"name": "N"}', context=json.dumps(QUIET)))
    assert fake_manager.calls == [("create", QUIET)]


@pytest.mark.parametrize("tool", ["create", "write", "message_post"])
def test_a_refused_key_reaches_nothing(fake_manager, tool):
    loud = json.dumps({"default_user_ids": [[6, 0, [1]]]})
    calls = {
        "create": lambda: crud.create(model="project.task", values="{}", context=loud),
        "write": lambda: crud.write(model="project.task", ids="[5]", values="{}", context=loud),
        "message_post": lambda: crud.message_post(
            model="project.task", res_id=5, body="<p>x</p>", context=loud,
        ),
    }
    with pytest.raises(ValueError, match="default_user_ids"):
        asyncio.run(calls[tool]())
    assert fake_manager.calls == []


def test_message_post_answers_with_the_message_and_the_record_link(fake_manager):
    result = asyncio.run(crud.message_post(
        model="project.task", res_id=5, body="<p>Done</p>", attachment_ids="[12]",
    ))
    assert result == {"id": 99, "_url": f"{WEB}/web#id=5&model=project.task&view_type=form"}
    assert fake_manager.calls == [("message_post", [12], None)]
