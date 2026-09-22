"""fields_get takes its attribute list as a keyword.

Through ``execute`` the dict travelled as the second positional argument, Odoo
iterated its keys as attribute names, and every field came back as ``{}``.
"""

from odoo_fast_mcp.connection import OdooConnectionManager


class _RecordingOdoo:
    def __init__(self):
        self.kw_calls = []

    def execute_kw(self, model, method, args, kwargs):
        self.kw_calls.append((model, method, args, kwargs))
        return {"name": {"string": "Name", "type": "char"}}

    def execute(self, *args):
        raise AssertionError(f"fields_get must go through execute_kw, got execute{args!r}")


def _connected_manager():
    manager = OdooConnectionManager()
    manager._odoo = _RecordingOdoo()
    manager._connected = True
    return manager


def test_fields_get_receives_attributes_as_a_keyword():
    manager = _connected_manager()
    result = manager.get_model_fields("res.partner", ["string", "help"])
    assert manager._odoo.kw_calls == [
        ("res.partner", "fields_get", [], {"attributes": ["string", "help"]}),
    ]
    assert result["name"]["string"] == "Name"


def test_default_attribute_list_when_none_given():
    manager = _connected_manager()
    manager.get_model_fields("res.partner")
    ((_, _, _, kwargs),) = manager._odoo.kw_calls
    assert kwargs == {"attributes": ["string", "type", "required", "readonly", "help", "relation"]}
