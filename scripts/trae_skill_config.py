#!/usr/bin/env python3
"""幂等注册/移除 ~/.trae-cn/skill-config.json 中的 super-memory skill。

Trae 只加载 managedSkills 里登记过的 skill；安装时把 skill 目录放到
~/.trae-cn/skills/super-memory/ 的同时，需要在 skill-config.json 的
managedSkills 中登记（类型 user_upload，与通过 Trae 界面上传一致）。

用法:
  trae_skill_config.py install --trae-home ~/.trae-cn
  trae_skill_config.py remove  --trae-home ~/.trae-cn

skill-config.json 不存在或不是合法 JSON 时不做任何改动，打印提示。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_NAME = "super-memory"
SKILL_TYPE = "user_upload"


def _config_path(trae_home: Path) -> Path:
    return trae_home / "skill-config.json"


def cmd_install(trae_home: Path) -> int:
    cfg = _config_path(trae_home)
    if not cfg.is_file():
        print(f"提示: {cfg} 不存在，跳过注册（请在 Trae 的技能设置中手动启用 super-memory）")
        return 1
    try:
        data = json.loads(cfg.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"提示: 无法解析 {cfg}（{e}），跳过注册；请手动在 managedSkills 中加入 "
              f'"{SKILL_NAME}": "{SKILL_TYPE}"')
        return 1
    if not isinstance(data, dict):
        print(f"提示: {cfg} 结构异常，跳过注册")
        return 1

    managed = data.setdefault("managedSkills", {})
    if not isinstance(managed, dict):
        print(f"提示: {cfg} 的 managedSkills 不是对象，跳过注册（请手动改为对象后重试）")
        return 1
    if managed.get(SKILL_NAME) == SKILL_TYPE:
        return 0
    managed[SKILL_NAME] = SKILL_TYPE
    tmp = cfg.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, cfg)
    return 0


def cmd_remove(trae_home: Path) -> int:
    cfg = _config_path(trae_home)
    if not cfg.is_file():
        return 0
    try:
        data = json.loads(cfg.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    managed = data.get("managedSkills")
    if isinstance(managed, dict) and SKILL_NAME in managed:
        del managed[SKILL_NAME]
        tmp = cfg.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cfg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "remove"])
    ap.add_argument("--trae-home", required=True)
    args = ap.parse_args()
    trae_home = Path(args.trae_home).expanduser()
    if args.action == "install":
        return cmd_install(trae_home)
    return cmd_remove(trae_home)


if __name__ == "__main__":
    sys.exit(main())
