import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "tools" / "demo" / "run_demo.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("demo_runner", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_exposes_callable_entrypoint():
    runner = _load_runner()

    assert callable(runner.run)


def test_terminal_cleanup_removes_ansi_controls_and_applies_backspace():
    runner = _load_runner()

    assert runner.clean_terminal_output("\x1b[31m红\x1b[0mX\bY\r\n") == "红Y\n"


def test_thinking_without_final_marker_is_rejected():
    runner = _load_runner()

    with pytest.raises(RuntimeError, match="无法可靠分隔"):
        runner.extract_final_explanation("Thinking...\n内部思考")


def test_delivery_wrap_adds_required_boundaries_deterministically():
    runner = _load_runner()

    delivery = runner.wrap_explanation("这是 Ollama 生成的正文。")

    assert "模型辅助内容" in delivery
    assert "内容定位推测，不等于真实粉丝画像" in delivery
    assert "公开页面快照，不代表账号后台真实曝光和转化" in delivery
    assert delivery.endswith("这是 Ollama 生成的正文。\n")


def test_model_body_rejects_metrics_and_causal_claims():
    runner = _load_runner()

    with pytest.raises(RuntimeError, match="禁止词"):
        runner.validate_model_body("四百四十六万粉丝导致完播数据极低。")


def test_model_body_accepts_neutral_transitions():
    runner = _load_runner()

    runner.validate_model_body(
        "先确认公开快照边界。\n"
        "再查看本次样本范围。\n"
        "接着说明指标计算口径。\n"
        "随后观察发布节奏。\n"
        "再进入内容定位观察。\n"
        "最后回到证据边界。"
    )
