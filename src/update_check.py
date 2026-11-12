# -*- coding: utf-8 -*-
"""comwel 새 버전 알림(알림만 하고 설치는 하지 않는다).

- Claude를 켤 때 뒤에서 하루 한 번 GitHub의 VERSION.json 을 읽어 설치된 버전과 비교한다.
- 새 버전이 있으면 검색 결과 아래에 알림 한 줄을 붙인다. 설치는 사용자가 "comwel 업데이트해 줘"라고 할 때만 한다.
  (GitHub에 올라온 코드가 사용자 확인 없이 실행되지 않도록 자동 설치는 일부러 넣지 않음)
- 환경변수 COMWEL_UPDATE_CHECK=0 이면 확인하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from store import Store

REMOTE_URL = "https://raw.githubusercontent.com/cplalks-create/comwel-mcp/master/VERSION.json"
REPO_URL = "https://github.com/cplalks-create/comwel-mcp"
LOCAL_FILE = Path(__file__).resolve().parent.parent / "VERSION.json"
INTERVAL = timedelta(days=1)
DISABLE_ENV = "COMWEL_UPDATE_CHECK"
META_KEY = "app_update"


VERSION_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(\.\d{1,3})?$")
API_URL_PREFIX = "https://www.data.go.kr/"


def _clean(value: object, limit: int) -> str:
    """한 줄짜리 짧은 글로 만든다(줄바꿈 제거, 길이 제한)."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def sanitize(data: object) -> dict | None:
    """GitHub에서 받은 버전 정보를 검증해 정해진 모양만 남긴다.

    이 정보는 알림 문구로 Claude에게 전달된다. 저장소가 탈취되어 이상한 글이 올라와도 알림을 통해
    긴 지시문이나 엉뚱한 주소가 전달되지 않도록, 버전 형식·글 길이·주소(공공데이터포털만)를 제한한다.
    """
    if not isinstance(data, dict):
        return None
    version = _clean(data.get("version"), 20)
    if not VERSION_RE.match(version):
        return None
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    apis = []
    for a in (data.get("new_api") if isinstance(data.get("new_api"), list) else [])[:5]:
        if isinstance(a, dict) and str(a.get("url", "")).startswith(API_URL_PREFIX):
            apis.append({"name": _clean(a.get("name"), 60), "url": _clean(a.get("url"), 120)})
    return {
        "version": version,
        "date": _clean(data.get("date"), 20),
        "summary": _clean(data.get("summary"), 120),
        "notes": [_clean(n, 160) for n in notes[:8] if _clean(n, 160)],
        "new_api": apis,
    }


def parse_version(v: str) -> tuple[int, ...]:
    """'2026.10.31' / '2026.10.31.2' → 비교용 숫자 묶음(형식이 틀리면 0)."""
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


def local_info() -> dict:
    """설치된 버전 정보."""
    try:
        return json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": "0"}


def fetch_remote(url: str = REMOTE_URL, timeout: int = 15) -> dict | None:
    """GitHub 최신 버전 정보(실패하면 None — 조용히 넘어감)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "comwel-mcp", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(20_000).decode("utf-8"))
    except Exception:
        return None


def disabled() -> bool:
    """알림을 껐는지."""
    return os.environ.get(DISABLE_ENV, "1").strip() == "0"


def check(store: Store, now: datetime | None = None, fetch: Callable[[], dict | None] = fetch_remote,
          force: bool = False) -> dict | None:
    """하루 한 번(force면 바로) 최신 버전을 확인해 보관한다. 보관된 최신 정보를 돌려준다."""
    if disabled() and not force:
        return None
    now = now or datetime.now()
    saved = store.get_meta(META_KEY) or {}
    last = saved.get("checked_ts")
    if not force and last:
        try:
            if now - datetime.fromisoformat(last) < INTERVAL:
                return saved.get("latest")
        except ValueError:
            pass
    remote = sanitize(fetch())
    record = {"checked_ts": now.isoformat(timespec="seconds"), "latest": remote or saved.get("latest")}
    store.set_meta(META_KEY, record)
    return record["latest"]


def latest_info(store: Store) -> dict | None:
    """보관된 최신 버전 정보(읽을 때도 한 번 더 검증)."""
    return sanitize((store.get_meta(META_KEY) or {}).get("latest"))


def notice(store: Store) -> str:
    """새 버전이 있으면 알림 문구, 없으면 빈 문자열."""
    if disabled():
        return ""
    latest = latest_info(store)
    if not latest:
        return ""
    mine = local_info().get("version", "0")
    if parse_version(latest["version"]) <= parse_version(mine):
        return ""
    msg = (f"[comwel 업데이트 알림] 새 버전 {latest['version']}이 있습니다(설치된 버전 {mine}). "
           f"저장소에 적힌 변경 요약: 「{latest['summary']}」. 이 사실을 사용자에게 한 줄로 알리고, "
           f"사용자가 원할 때만 \"comwel 업데이트해 줘\"로 설치합니다(INSTALL_FOR_CLAUDE.md 업데이트 절차).")
    if latest["new_api"]:
        msg += " 새로 활용신청할 API: " + ", ".join(f"{a['name']}({a['url']})" for a in latest["new_api"])
    return msg


def status_text(store: Store) -> str:
    """버전 상태 설명(check_update 도구용)."""
    mine = local_info()
    saved = store.get_meta(META_KEY) or {}
    latest = latest_info(store)
    lines = [f"- 설치된 버전: {mine.get('version')} ({mine.get('summary', '')})"]
    if latest:
        lines.append(f"- GitHub 최신 버전: {latest.get('version')} ({latest.get('date', '')})")
        if parse_version(latest.get("version", "0")) > parse_version(mine.get("version", "0")):
            lines.append("- 새 버전이 있습니다. 바뀐 내용:")
            lines += [f"  · {n}" for n in latest.get("notes", [])]
            for a in latest.get("new_api") or []:
                lines.append(f"  · 새로 활용신청 필요: {a.get('name')} {a.get('url')}")
            lines.append("- 설치: \"comwel 업데이트해 줘\" (INSTALL_FOR_CLAUDE.md 업데이트 절차). 판례 보관본과 인증키는 그대로 유지됩니다.")
        else:
            lines.append("- 최신 버전을 쓰고 있습니다.")
    else:
        lines.append("- GitHub 최신 버전을 확인하지 못했습니다(인터넷 연결 확인).")
    if saved.get("checked_ts"):
        lines.append(f"- 마지막 확인: {saved['checked_ts'].replace('T', ' ')}")
    if disabled():
        lines.append(f"- 자동 알림: 꺼짐({DISABLE_ENV}=0)")
    lines.append(f"- 저장소: {REPO_URL}")
    return "\n".join(lines)


def start_background(store_path: str, delay_sec: float = 8.0) -> threading.Thread:
    """서버 시작을 늦추지 않도록 별도 스레드에서 확인."""
    def worker() -> None:
        time.sleep(delay_sec)
        try:
            check(Store(store_path))
        except Exception as exc:  # 알림 확인 문제로 서버가 멈추면 안 됨
            print(f"[comwel 업데이트 확인] 무시한 오류: {exc!r}", file=sys.stderr, flush=True)

    th = threading.Thread(target=worker, name="comwel-update-check", daemon=True)
    th.start()
    return th
