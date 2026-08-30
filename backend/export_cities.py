"""把亚朵已开业城市列表导出为 frontend/public/atour-cities.json 快照。

数据源：亚朵官方接口 /atourlife/city/listOfChain（见 services/atour_api.py 的
get_atour_cities）。本脚本供 GitHub Actions 定时任务调用，实现目的地列表的
「定期更新」；也可本地手动执行：

    cd backend && python export_cities.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# 允许在任意 cwd 下运行：把 backend 目录加入 sys.path，确保能导入 services 包。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from services.atour_api import AtourAPIError, get_atour_cities  # noqa: E402


def _target_path() -> str:
    """frontend/public/atour-cities.json 的绝对路径（backend/../frontend/...）。"""
    root = os.path.dirname(_HERE)  # backend 的上一级 = 项目根
    return os.path.join(root, "frontend", "public", "atour-cities.json")


def _now_utc() -> str:
    """当前 UTC 时间，格式：2026-08-30T04:00:00Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    target = _target_path()
    try:
        # force=True 绕过进程内缓存，强制实时拉取最新城市列表
        data = get_atour_cities(force=True)
    except AtourAPIError as exc:
        print(f"[export_cities] 获取城市列表失败：{exc}", file=sys.stderr)
        return 1

    if not data:
        print("[export_cities] 接口未返回任何城市，跳过写入。", file=sys.stderr)
        return 1

    total = sum(len(v) for v in data.values())
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # JSON 不支持注释，改用顶层 _updated_at 元字段记录本次更新时间：
    # 该值每次运行都会变化，保证「每次跑 action 都产生一次提交并重新部署」。
    # 前端解析时会忽略此字段（见 SearchBox.astro 的 provinceNames/cityNames）。
    payload = {"_updated_at": _now_utc(), **data}
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"[export_cities] 已导出 {len(data)} 个省 / {total} 个城市 -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
