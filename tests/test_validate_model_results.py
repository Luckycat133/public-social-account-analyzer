"""Regression tests for standalone model-result validation contracts."""

import analyze
import task_contract as contract
import validate_model_results as validator


def test_enum_alignment():
    tax_format = getattr(contract, "TAX_FORMAT", None)
    tax_funnel = getattr(contract, "TAX_FUNNEL", None)
    tax_hook = getattr(contract, "TAX_HOOK", None)
    assert tax_format is not None
    assert tax_funnel is not None
    assert tax_hook is not None
    assert getattr(validator, "TAX_FORMAT", None) is tax_format
    assert getattr(validator, "TAX_FUNNEL", None) is tax_funnel
    assert getattr(validator, "TAX_HOOK", None) is tax_hook
    assert analyze._TAX_FORMAT is tax_format
    assert analyze._TAX_FUNNEL is tax_funnel
    assert analyze._TAX_HOOK is tax_hook
