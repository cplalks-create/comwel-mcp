# -*- coding: utf-8 -*-
"""판례 보관본 자동 갱신 확인.

MCP 서버가 켜질 때(= Claude를 켤 때) 뒤에서 한 번 실행된다.
- 마지막 확인 후 7일이 안 지났으면 아무것도 하지 않는다(공단 서버 호출 0번).
- 7일이 지났으면 공단 서버에 판례 총건수만 묻는다(호출 1번).
  건수가 보관본과 다르면 전체를 다시 받는다(호출 약 35번, 1~2분).
- 마지막으로 전체를 받은 지 30일이 지났으면 건수와 상관없이 다시 받는다
  (API에 날짜 칸이 없어, 건수는 같고 내용만 고쳐진 경우를 알아낼 방법이 없기 때문).
- 받는 동안에도 검색은 기존 보관본으로 계속된다(WAL). 실패하면 기존 보관본을 그대로 두고 하루 뒤 다시 시도한다.
- Claude 창이 여러 개여도 잠금 파일로 한 곳에서만 받는다.
- 환경변수 COMWEL_AUTO_UPDATE=0 이면 끈다.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from api_client import ComwelApiError, ComwelClient
from store import Store, now_text
from sync_precedents import sync_precedents

CHECK_INTERVAL = timedelta(days=7)    # 건수 확인 주기
FORCE_INTERVAL = timedelta(days=30)   # 건수와 상관없이 다시 받는 주기
RETRY_AFTER_ERROR = timedelta(days=1)
LOCK_STALE = timedelta(minutes=30)    # 이보다 오래된 잠금 파일은 비정상 종료로 보고 지움
LOG_LIMIT = 30
DISABLE_ENV = "COMWEL_AUTO_UPDATE"


def log(msg: str) -> None:
    """표준오류로 기록(MCP 통신은 표준출력을 쓰므로 섞으면 안 됨)."""
    print(f"[comwel 자동 갱신] {msg}", file=sys.stderr, flush=True)


def parse_time(info: object) -> datetime | None:
    """meta 값에서 시각을 읽는다('ts' ISO 형식, 없으면 'at' 표시 형식 "2026. 10. 30. 21:23")."""
    if not isinstance(info, dict):
        return None
    ts = info.get("ts")
    if ts:
        try:
            return datetime.fromisoformat(str(ts))
        except ValueError:
            pass
    m = re.match(r"(\d{4})\. (\d{1,2})\. (\d{1,2})\. (\d{1,2}):(\d{2})", str(info.get("at", "")))
    if m:
        return datetime(*map(int, m.groups()))
    return None


def decide(now: datetime, stored_count: int, last_sync: datetime | None, last_check: datetime | None,
           api_total: Callable[[], int]) -> tuple[str, str]:
    """할 일을 정한다. ('sync'=다시 받기 | 'none'=확인만 함 | 'skip'=아직 확인할 때 아님, 사유)

    api_total 은 건수 확인이 필요할 때만 부른다.
    """
    if stored_count == 0:
        return "sync", "보관본이 비어 있음"
    if last_check and now - last_check < CHECK_INTERVAL:
        return "skip", "마지막 확인 후 7일이 지나지 않음"
    if last_sync is None or now - last_sync >= FORCE_INTERVAL:
        return "sync", "30일 정기 갱신"
    total = api_total()
    if total != stored_count:
        return "sync", f"공단 판례 건수 변경({stored_count:,} → {total:,})"
    return "none", f"변경 없음({total:,}건)"


class FileLock:
    """여러 Claude 창(여러 MCP 프로세스)이 동시에 받지 않도록 하는 잠금 파일."""

    def __init__(self, path: Path) -> None:
        """잠금 파일 경로."""
        self.path = path
        self.held = False

    def is_locked(self) -> bool:
        """누군가 받는 중인지(오래된 잠금은 무시)."""
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age < LOCK_STALE.total_seconds()

    def acquire(self) -> bool:
        """잠금을 잡는다. 이미 다른 곳에서 잡고 있으면 False."""
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}".encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                if self.is_locked():
                    return False
                try:  # 비정상 종료로 남은 잠금 → 지우고 한 번 더
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        return False

    def release(self) -> None:
        """잠금을 푼다."""
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.held = False


def lock_for(store: Store) -> FileLock:
    """보관본 옆의 잠금 파일."""
    return FileLock(Path(store.path).with_suffix(".lock"))


def record(store: Store, now: datetime, action: str, reason: str, next_ts: datetime | None = None) -> None:
    """확인 결과를 남긴다(다음 확인 시점 계산용 + 최근 기록 30건)."""
    store.set_meta("precedent_check", {
        "ts": (next_ts or now).isoformat(timespec="seconds"), "action": action, "reason": reason})
    history = store.get_meta("precedent_check_log", [])
    if not isinstance(history, list):
        history = []
    history.append({"at": now_text(), "action": action, "reason": reason})
    store.set_meta("precedent_check_log", history[-LOG_LIMIT:])


def run_auto_update(client: ComwelClient, store: Store, now: datetime | None = None) -> tuple[str, str]:
    """자동 갱신 확인을 한 번 실행한다. (할 일, 사유)를 돌려준다."""
    if os.environ.get(DISABLE_ENV, "1").strip() == "0":
        return "off", f"{DISABLE_ENV}=0 으로 꺼져 있음"
    now = now or datetime.now()
    lock = lock_for(store)
    if not lock.acquire():
        return "busy", "다른 Claude 창에서 갱신 중"
    try:
        last_sync = parse_time(store.get_meta("precedent_sync"))
        checked = parse_time(store.get_meta("precedent_check"))
        last_check = max((t for t in (last_sync, checked) if t), default=None)
        action, reason = decide(now, store.precedent_count(), last_sync, last_check,
                                lambda: client.precedent_page(1, 1)[0])
        if action == "skip":
            return action, reason
        if action == "sync":
            log(f"판례 보관본을 다시 받습니다 — {reason}")
            info = sync_precedents(client, store)
            reason = f"{reason} → {info['count']:,}건으로 갱신"
        record(store, now, action, reason)
        log(reason)
        return action, reason
    except ComwelApiError as exc:
        # 기존 보관본은 그대로. 하루 뒤 다시 시도하도록 확인 시각을 앞당겨 적는다
        reason = f"실패(기존 보관본 유지): {exc}"
        record(store, now, "error", reason, next_ts=now - CHECK_INTERVAL + RETRY_AFTER_ERROR)
        log(reason)
        return "error", reason
    finally:
        lock.release()


def start_background(store_path: str, delay_sec: float = 5.0) -> threading.Thread:
    """서버 시작을 늦추지 않도록 별도 스레드에서 자동 갱신 확인을 실행한다."""
    def worker() -> None:
        time.sleep(delay_sec)
        try:
            run_auto_update(ComwelClient(), Store(store_path))
        except Exception as exc:  # 자동 갱신 문제로 서버가 죽으면 안 됨
            log(f"예상하지 못한 오류(무시하고 계속): {exc!r}")

    th = threading.Thread(target=worker, name="comwel-auto-update", daemon=True)
    th.start()
    return th


def status_text(store: Store, now: datetime | None = None) -> str:
    """자동 갱신 상태 한 줄."""
    if os.environ.get(DISABLE_ENV, "1").strip() == "0":
        return "자동 갱신: 꺼짐"
    if lock_for(store).is_locked():
        return "자동 갱신: 지금 최신 판례를 받는 중(1~2분, 검색은 기존 보관본으로 계속됨)"
    now = now or datetime.now()
    last_sync = parse_time(store.get_meta("precedent_sync"))
    chk = store.get_meta("precedent_check")
    checked = parse_time(chk)
    last_check = max((t for t in (last_sync, checked) if t), default=None)
    if not last_check:
        return "자동 갱신: 다음에 Claude를 켤 때 확인"
    nxt = last_check + CHECK_INTERVAL
    nxt_text = "다음에 Claude를 켤 때" if nxt <= now else f"{nxt.year}. {nxt.month}. {nxt.day}. 이후"
    last = f" (마지막 확인 결과: {chk.get('reason')})" if isinstance(chk, dict) and chk.get("reason") else ""
    return f"자동 갱신: 다음 확인 {nxt_text}{last}"
