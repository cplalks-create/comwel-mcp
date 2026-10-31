# -*- coding: utf-8 -*-
"""새 버전 알림 테스트(가짜 GitHub 응답, 임시 DB, 인터넷 불필요)."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import update_check  # noqa: E402
from store import Store  # noqa: E402

NOW = datetime(2026, 11, 5, 9, 0)


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """설치된 버전이 2026.10.31 인 상태."""
    local = tmp_path / "VERSION.json"
    local.write_text(json.dumps({"version": "2026.10.31", "summary": "현재"}), encoding="utf-8")
    monkeypatch.setattr(update_check, "LOCAL_FILE", local)
    monkeypatch.delenv(update_check.DISABLE_ENV, raising=False)
    return Store(tmp_path / "t.sqlite")


class Fake:
    """가짜 GitHub 응답(호출 횟수 기록)."""

    def __init__(self, data: dict | None) -> None:
        """돌려줄 값."""
        self.data, self.calls = data, 0

    def __call__(self) -> dict | None:
        """호출."""
        self.calls += 1
        return self.data


NEWER = {"version": "2026.11.3", "date": "2026. 11. 3.", "summary": "새 기능", "notes": ["A 추가"],
         "new_api": [{"name": "예시 API", "url": "https://www.data.go.kr/data/1/openapi.do"}]}


def test_parse_version_order() -> None:
    """날짜형 버전 비교(같은 날 두 번째 배포 포함)."""
    pv = update_check.parse_version
    assert pv("2026.11.3") > pv("2026.10.31")
    assert pv("2026.10.31.2") > pv("2026.10.31")
    assert pv("엉터리") == (0,)


def test_newer_version_shows_notice_with_new_api(store: Store) -> None:
    """새 버전이면 알림과 새로 활용신청할 API를 보여 준다."""
    update_check.check(store, NOW, Fake(NEWER))
    msg = update_check.notice(store)
    assert "2026.11.3" in msg and "업데이트해 줘" in msg and "예시 API" in msg


def test_same_version_no_notice(store: Store) -> None:
    """같은 버전이면 알림 없음."""
    update_check.check(store, NOW, Fake({"version": "2026.10.31"}))
    assert update_check.notice(store) == ""


def test_checks_only_once_a_day(store: Store) -> None:
    """하루에 한 번만 GitHub를 확인한다(force면 바로)."""
    f = Fake(NEWER)
    update_check.check(store, NOW, f)
    update_check.check(store, NOW + timedelta(hours=5), f)
    assert f.calls == 1
    update_check.check(store, NOW + timedelta(hours=25), f)
    assert f.calls == 2
    update_check.check(store, NOW + timedelta(hours=26), f, force=True)
    assert f.calls == 3


def test_network_failure_keeps_previous_info(store: Store) -> None:
    """인터넷이 안 되면 조용히 넘어가고, 이전에 받은 정보는 유지."""
    update_check.check(store, NOW, Fake(NEWER))
    update_check.check(store, NOW + timedelta(days=2), Fake(None))
    assert "2026.11.3" in update_check.notice(store)


def test_disabled_by_env(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """COMWEL_UPDATE_CHECK=0 이면 확인도 알림도 하지 않는다."""
    update_check.check(store, NOW, Fake(NEWER))
    monkeypatch.setenv(update_check.DISABLE_ENV, "0")
    f = Fake(NEWER)
    assert update_check.check(store, NOW + timedelta(days=3), f) is None and f.calls == 0
    assert update_check.notice(store) == ""


def test_status_text_lists_changes(store: Store) -> None:
    """확인 도구 문구에 바뀐 내용·활용신청·설치 방법."""
    update_check.check(store, NOW, Fake(NEWER))
    text = update_check.status_text(store)
    assert "A 추가" in text and "새로 활용신청 필요" in text and "업데이트해 줘" in text


def test_repo_version_file_is_valid() -> None:
    """저장소의 VERSION.json 형식 확인(배포 전 실수 방지)."""
    data = json.loads((Path(__file__).resolve().parent.parent / "VERSION.json").read_text(encoding="utf-8"))
    assert update_check.parse_version(data["version"]) != (0,)
    assert data["summary"] and isinstance(data["notes"], list) and isinstance(data["new_api"], list)
