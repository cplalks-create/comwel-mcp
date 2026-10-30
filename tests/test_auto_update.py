# -*- coding: utf-8 -*-
"""판례 보관본 자동 갱신 테스트(가짜 공단 서버, 임시 DB, 인터넷 불필요)."""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import auto_update  # noqa: E402
from api_client import ComwelApiError  # noqa: E402
from store import Store  # noqa: E402

NOW = datetime(2026, 11, 20, 9, 0)


class FakeClient:
    """판례 API 흉내. total=공단 총건수, fail=True면 오류."""

    def __init__(self, total: int, fail: bool = False) -> None:
        """호출 횟수를 센다."""
        self.total, self.fail, self.calls = total, fail, 0

    def precedent_page(self, page: int, size: int) -> tuple[int, list[dict[str, str]]]:
        """한 쪽 분량."""
        self.calls += 1
        if self.fail:
            raise ComwelApiError("공단 서버 점검 중")
        start = (page - 1) * size
        n = max(0, min(size, self.total - start))
        return self.total, [{"accnum": f"{start + i}", "noncontent": "본문"} for i in range(n)]


def make_store(tmp_path: Path, count: int, synced: datetime | None, checked: datetime | None = None) -> Store:
    """count건이 synced 시각에 받아진 보관본."""
    s = Store(tmp_path / "comwel.sqlite")
    if count:
        s.replace_precedents([{"accnum": str(i), "noncontent": "옛 본문"} for i in range(count)])
    if synced:
        s.set_meta("precedent_sync", {"at": "x", "ts": synced.isoformat(), "count": count, "api_total": count})
    if checked:
        s.set_meta("precedent_check", {"ts": checked.isoformat(), "action": "none", "reason": ""})
    return s


def test_within_7_days_makes_no_api_call(tmp_path: Path) -> None:
    """마지막 확인 후 7일 이내면 공단 서버를 부르지 않는다."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=6))
    c = FakeClient(3)
    assert auto_update.run_auto_update(c, s, NOW)[0] == "skip"
    assert c.calls == 0


def test_after_7_days_same_count_only_checks(tmp_path: Path) -> None:
    """7일이 지났고 건수가 같으면 건수만 확인(호출 1번)하고 다시 받지 않는다."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=8))
    c = FakeClient(3)
    action, reason = auto_update.run_auto_update(c, s, NOW)
    assert action == "none" and "변경 없음" in reason
    assert c.calls == 1
    assert s.db.execute("SELECT content FROM precedent LIMIT 1").fetchone()[0] == "옛 본문"
    # 확인 기록이 남아 다음 7일은 다시 부르지 않음
    assert auto_update.run_auto_update(c, s, NOW + timedelta(days=3))[0] == "skip"
    assert c.calls == 1


def test_count_changed_triggers_full_sync(tmp_path: Path) -> None:
    """건수가 바뀌면 전체를 다시 받는다."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=8))
    c = FakeClient(5)
    action, reason = auto_update.run_auto_update(c, s, NOW)
    assert action == "sync" and "3 → 5" in reason
    assert s.precedent_count() == 5


def test_30_days_forces_sync_even_if_same_count(tmp_path: Path) -> None:
    """30일이 지나면 건수가 같아도 다시 받는다(내용 정정 대비)."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=31), checked=NOW - timedelta(days=8))
    c = FakeClient(3)
    action, reason = auto_update.run_auto_update(c, s, NOW)
    assert action == "sync" and "30일" in reason
    assert s.db.execute("SELECT content FROM precedent LIMIT 1").fetchone()[0] == "본문"


def test_empty_store_syncs_immediately(tmp_path: Path) -> None:
    """보관본이 비어 있으면 바로 받는다(설치 때 건너뛴 경우)."""
    s = make_store(tmp_path, 0, synced=None)
    assert auto_update.run_auto_update(FakeClient(4), s, NOW)[0] == "sync"
    assert s.precedent_count() == 4


def test_failure_keeps_data_and_retries_next_day(tmp_path: Path) -> None:
    """공단 서버 오류면 기존 보관본을 지키고, 하루 뒤 다시 시도한다."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=8))
    action, _ = auto_update.run_auto_update(FakeClient(9, fail=True), s, NOW)
    assert action == "error" and s.precedent_count() == 3
    c = FakeClient(3)
    assert auto_update.run_auto_update(c, s, NOW + timedelta(hours=12))[0] == "skip"
    assert auto_update.run_auto_update(c, s, NOW + timedelta(days=1, minutes=1))[0] == "none"
    log = s.get_meta("precedent_check_log")
    assert [h["action"] for h in log] == ["error", "none"]


def test_lock_prevents_parallel_sync_and_stale_lock_is_cleared(tmp_path: Path) -> None:
    """다른 창이 받는 중이면 건너뛰고, 30분 넘은 잠금은 비정상 종료로 보고 지운다."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=8))
    lock = auto_update.lock_for(s)
    assert lock.acquire()
    c = FakeClient(5)
    assert auto_update.run_auto_update(c, s, NOW)[0] == "busy" and c.calls == 0
    old = time.time() - 31 * 60
    os.utime(lock.path, (old, old))
    assert auto_update.run_auto_update(c, s, NOW)[0] == "sync"
    assert not lock.path.exists()


def test_disable_with_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """COMWEL_AUTO_UPDATE=0 이면 아무것도 하지 않는다."""
    monkeypatch.setenv("COMWEL_AUTO_UPDATE", "0")
    s = make_store(tmp_path, 0, synced=None)
    c = FakeClient(4)
    assert auto_update.run_auto_update(c, s, NOW)[0] == "off" and c.calls == 0


def test_old_meta_without_ts_is_understood() -> None:
    """예전 형식(at만 있는 기록)도 시각으로 읽는다."""
    assert auto_update.parse_time({"at": "2026. 10. 30. 21:23"}) == datetime(2026, 10, 30, 21, 23)
    assert auto_update.parse_time(None) is None


def test_status_text(tmp_path: Path) -> None:
    """상태 문구: 다음 확인 날짜와 받는 중 표시."""
    s = make_store(tmp_path, 3, synced=NOW - timedelta(days=2))
    assert "2026. 11. 25. 이후" in auto_update.status_text(s, NOW)
    lock = auto_update.lock_for(s)
    lock.acquire()
    assert "받는 중" in auto_update.status_text(s, NOW)
    lock.release()
