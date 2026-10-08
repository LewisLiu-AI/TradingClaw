"""仓库回测框架入口 (shim)。

仓库 runner 要求 ``run_dir/config.json`` + ``run_dir/code/signal_engine.py``,
且该文件的顶层不得有可执行语句 —— 所以这里只做"加载真实实现"的薄封装,
真实策略逻辑在 ``reports/301526_swing_study/signal_engine.py``。

前置: 需在 ``~/.vibe-trading/data-bridge/config.yaml`` 注册本地 CSV
(见 REPORT.md「复现方式」给的片段), 把 301526.SZ 指向 data/px_qfq.csv。

运行: cd reports/301526_swing_study && python -m backtest.runner run
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _real_path() -> Path:
    return Path(__file__).resolve().parents[2] / "signal_engine.py"


def _load_real():
    spec = importlib.util.spec_from_file_location("swing_real_engine", _real_path())
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SignalEngine:
    """把本地 CSV 特征 -> 目标仓位, 契约: generate(data_map) -> {code: Series}。"""

    def generate(self, data_map: dict) -> dict:
        return _load_real().SignalEngine().generate(data_map)
