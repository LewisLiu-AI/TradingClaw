"""CLI 演示: 打印最新信号与回测摘要(独立于 signal_engine.py, 便于框架加载)。

用法: python run_swing.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import signal_engine as se


def main() -> None:
    df = se.build_features()
    tgt = se.generate_target(df)
    sig = se.sub_signals(df)
    last = df.index[-1]
    print(f"标的: 301526.SZ 国际复材   数据截止: {last.date()}  收盘 {df['close'].iloc[-1]:.2f}")
    print(f"当前建议仓位: {tgt.iloc[-1] * 100:.0f}%")
    print(f"状态: {'持仓' if tgt.iloc[-1] > 0 else '空仓'} | "
          f"趋势(MA20>MA60): {'是' if df['ma20'].iloc[-1] > df['ma60'].iloc[-1] else '否'} | "
          f"距MA20 {df['dist_ma20'].iloc[-1]:+.1f}% | RSI14 {df['rsi14'].iloc[-1]:.0f} | "
          f"距20日高点 {df['dd_high20'].iloc[-1]:+.1f}%")
    print("\n近10日信号:")
    cols = ["close", "dist_ma20", "rsi14", "dd_high20", "vol_ratio"]
    sig_cols = ["A_pullback", "B1_panic", "B2_crash", "B3_snapback", "C_breakout", "n_derisk"]
    show = pd.concat([df[cols], sig[sig_cols], tgt.rename("target")], axis=1).tail(10)
    print(show.round(2).to_string())
    JSON = {"as_of": str(last.date()), "close": float(df["close"].iloc[-1]),
            "target_position": float(tgt.iloc[-1]),
            "above_ma20": bool(df["close"].iloc[-1] > df["ma20"].iloc[-1]),
            "ma20_gt_ma60": bool(df["ma20"].iloc[-1] > df["ma60"].iloc[-1])}
    Path("latest_signal.json").write_text(json.dumps(JSON, ensure_ascii=False, indent=2))
    print("\n-> latest_signal.json")


if __name__ == "__main__":
    main()
