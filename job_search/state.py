"""Persistence for previously seen jobs and run history, backing:
 - dedup/announcement suppression across runs
 - re-validation of previously seen roles (prompt requirement)
 - the every-other-day self-check that main.py enforces
"""
import json
import os
from datetime import date, datetime
from typing import Optional

DEFAULT_STATE = {"schema_version": 1, "runs": [], "jobs": {}}


def load(path: str) -> dict:
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_STATE))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("runs", [])
    data.setdefault("jobs", {})
    return data


def save(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def last_run_date(state: dict) -> Optional[str]:
    successful = [r for r in state["runs"] if r.get("status") == "success"]
    if not successful:
        return None
    return sorted(r["date"] for r in successful)[-1]


def days_since_last_run(state: dict, today: date = None) -> Optional[int]:
    last = last_run_date(state)
    if last is None:
        return None
    today = today or date.today()
    return (today - datetime.strptime(last, "%Y-%m-%d").date()).days


def record_run(state: dict, run_date: str, status: str, found: int) -> None:
    state["runs"].append({"date": run_date, "status": status, "found": found})


def upsert_job(state: dict, key: str, record: dict, today: str) -> None:
    existing = state["jobs"].get(key)
    first_seen = existing["first_seen"] if existing else today
    record = dict(record)
    record["first_seen"] = first_seen
    record["last_verified"] = today
    state["jobs"][key] = record


def remove_job(state: dict, key: str) -> None:
    state["jobs"].pop(key, None)


def all_job_keys(state: dict):
    return list(state["jobs"].keys())
