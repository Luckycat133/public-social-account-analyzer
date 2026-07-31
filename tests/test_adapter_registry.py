"""Adapter registry contracts for extensible, diagnosable collector loading."""

from __future__ import annotations

import types


def test_registry_loads_supported_collectors_and_reports_constructor_failures(
    monkeypatch,
):
    from collectors.adapter_registry import AdapterSettings, load_adapters
    import collectors.adapter_registry as registry

    class WorkingCollector:
        platform = "working"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class BrokenCollector:
        platform = "broken"

        def __init__(self, **kwargs):
            raise RuntimeError("private transport detail")

    modules = {
        "collectors.working": types.SimpleNamespace(WorkingCollector=WorkingCollector),
        "collectors.broken": types.SimpleNamespace(BrokenCollector=BrokenCollector),
    }
    monkeypatch.setattr(registry.importlib, "import_module", modules.__getitem__)
    monkeypatch.setattr(
        registry,
        "ADAPTER_SPECS",
        (
            registry.AdapterSpec("working", "collectors.working", "WorkingCollector"),
            registry.AdapterSpec("broken", "collectors.broken", "BrokenCollector"),
        ),
    )

    result = load_adapters(AdapterSettings())

    assert [adapter.platform for adapter in result.adapters] == ["working"]
    assert result.failures == ("broken",)
