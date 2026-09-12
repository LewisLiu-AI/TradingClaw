#!/usr/bin/env python3
"""列出服务**实际**会加载的技能 —— 排查"技能装了但看不到"用。

为什么需要它：技能有两个来源，且取决于运行身份。
  · 用户技能:  <服务用户 HOME>/.vibe-trading/skills/user/     ← 用户自建能力放这里
  · 内置技能:  <repo>/agent/src/skills/                       ← 产品自带, 勿放自建能力
  SkillsLoader 先扫用户目录, 同名时用户技能覆盖内置技能。
所以"以 root 跑"和"以服务用户 vibe 跑"看到的列表可能不同 —— 必须用**服务身份**检查。

用法:
    python scripts/check_skills.py                 # 以当前身份
    su -s /bin/bash vibe -c '/opt/vibe-trading/venv/bin/python /opt/vibe-trading/scripts/check_skills.py'
    python scripts/check_skills.py --name ashare-data-lab      # 只看某个技能
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None, help="只打印匹配的技能")
    args = ap.parse_args()

    sys.path.insert(0, str(AGENT))
    try:
        from src.agent.skills import SkillsLoader, USER_SKILLS_DIR, default_bundled_skills_dir
    except Exception as exc:  # noqa: BLE001
        print(f"无法导入 SkillsLoader: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"运行身份      : uid={__import__('os').getuid()} HOME={Path.home()}")
    print(f"用户技能目录  : {USER_SKILLS_DIR}  {'(存在)' if USER_SKILLS_DIR.exists() else '(不存在)'}")
    print(f"内置技能目录  : {default_bundled_skills_dir()}  {'(存在)' if default_bundled_skills_dir().exists() else '(不存在)'}")

    loader = SkillsLoader()
    skills = loader.skills
    print(f"\n实际加载技能数: {len(skills)}")
    if args.name:
        hits = [s for s in skills if args.name in s.name]
        if not hits:
            print(f"⚠️ 没有匹配 '{args.name}' 的技能 —— 检查是否放错目录(自建能力应放用户技能目录)")
            sys.exit(2)
        for s in hits:
            print(f"  {s.name}\n    来源: {s.dir_path}")
        return

    user_dir = USER_SKILLS_DIR
    for s in skills:
        src = "user" if s.dir_path and user_dir in s.dir_path.parents else "bundled"
        flag = " ←" if src == "user" else ""
        print(f"  [{src:7s}] {s.name}{flag}")


if __name__ == "__main__":
    main()
