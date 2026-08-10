from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Callable, TypeVar

import pandas as pd

T = TypeVar("T")


def retry(call: Callable[[], T], attempts: int = 4, delay: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay * attempt)
    assert last_error is not None
    raise last_error


def normalize_code(value: object) -> str:
    text = str(value).strip().split(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def append_history(path: Path, row: dict[str, object], key: str = "date") -> pd.DataFrame:
    ensure_dir(path.parent)
    fresh = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path, encoding="utf-8-sig")
        data = pd.concat([old, fresh], ignore_index=True)
    else:
        data = fresh
    data = data.drop_duplicates(subset=[key], keep="last").sort_values(key)
    data.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return data
