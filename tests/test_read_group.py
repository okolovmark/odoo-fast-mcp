"""Counts and totals per group have a read-only tool of their own.

Without one, "how many per department" went through `execute` `read_group`,
and `execute` is confirmed on every call: a question that reads nothing but
aggregates asked for the same approval as an `unlink`.
"""

import asyncio

import odoo_fast_mcp.tools.crud as crud
from odoo_fast_mcp.connection import OdooConnectionManager

GROUPS = [{"department_id": [3, "Production"], "__count": 12, "__domain": [["department_id", "=", 3]]}]


class _Model:
    def __init__(self, calls):
        self._calls = calls

    def read_group(self, *args, **kwargs):
        self._calls.append((args, kwargs))
        return GROUPS


class _RecordingOdoo:
    def __init__(self):
        self.calls = []
        self.env = {"maintenance.equipment": _Model(self.calls)}


def test_the_manager_sends_paging_and_order_as_keywords():
    manager = OdooConnectionManager()
    manager._odoo = _RecordingOdoo()
    manager._connected = True

    result = manager.read_group(
        "maintenance.equipment", [], ["cost:sum"], ["department_id"], limit=5, lazy=False,
    )
    assert result == GROUPS
    assert manager._odoo.calls == [
        (([], ["cost:sum"], ["department_id"]),
         {"offset": 0, "limit": 5, "orderby": False, "lazy": False}),
    ]


class _FakeManager:
    def __init__(self):
        self.calls = []

    def read_group(self, **kwargs):
        self.calls.append(kwargs)
        return GROUPS


def test_the_tool_counts_every_group_in_one_call_by_default(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(crud, "odoo_manager", fake)

    result = asyncio.run(crud.read_group(
        model="maintenance.equipment", groupby='["department_id", "category_id"]',
    ))
    assert result == GROUPS
    assert fake.calls == [{
        "model": "maintenance.equipment",
        "domain": [],
        # `[]` would make Odoo sum every numeric field, ids included.
        "fields": ["__count"],
        "groupby": ["department_id", "category_id"],
        "offset": 0,
        "limit": None,
        "orderby": None,
        "lazy": False,
    }]
