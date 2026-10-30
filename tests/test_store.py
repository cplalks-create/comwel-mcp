# -*- coding: utf-8 -*-
"""저장소 단위 테스트(임시 DB, 인터넷 불필요)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api_client import ComwelApiError  # noqa: E402
from store import Store  # noqa: E402
from sync_precedents import sync_precedents  # noqa: E402

ROWS = [
    {"accnum": "2021구합80100", "courtname": "서울행정법원", "title": "요양불승인처분취소",
     "kinda": "기각", "kindb": "요양", "kindc": "업무상질병", "noncontent": "급식실 조리\n흄에 노출되어 폐암이 발병"},
    {"accnum": "(창원)2018누10708", "courtname": "부산고등법원", "title": "요양불승인처분취소",
     "kinda": "기각", "kindb": "요양", "kindc": "업무상질병", "noncontent": "통행료 수납 업무, 뇌출혈"},
    {"accnum": "2019두1", "courtname": "대법원", "title": "유족급여부지급처분취소",
     "kinda": "파기환송", "kindb": "유족", "kindc": "업무상사고", "noncontent": "출장 중 교통사고"},
]


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    """임시 DB에 표본 판례 3건."""
    s = Store(tmp_path / "t.sqlite")
    s.replace_precedents(ROWS)
    return s


def test_search_by_words_ignoring_linebreak(store: Store) -> None:
    """줄바꿈으로 끊긴 '조리흄'도 찾는다."""
    total, rows = store.search_precedents(["조리흄", "폐암"], [])
    assert total == 1 and rows[0]["accnum"] == "2021구합80100"


def test_search_filters_and_exclude(store: Store) -> None:
    """분류 조건·법원·제외어."""
    assert store.search_precedents([], [], kinda="기각")[0] == 2
    assert store.search_precedents([], [], court="대법원")[0] == 1
    assert store.search_precedents([], ["뇌출혈"], kindb="요양")[0] == 1
    assert store.search_precedents(["없는말"], [])[0] == 0


def test_paging(store: Store) -> None:
    """쪽 나누기."""
    total, rows = store.search_precedents([], [], offset=2, limit=2)
    assert total == 3 and len(rows) == 1


def test_get_precedent_with_branch_prefix(store: Store) -> None:
    """'(창원)' 없이 번호만 넣어도 찾는다."""
    assert store.get_precedents("(창원)2018누10708")[0]["courtname"] == "부산고등법원"
    assert store.get_precedents("2018누10708")[0]["courtname"] == "부산고등법원"
    assert store.get_precedents("2099누1") == []


def test_jilbyeong_cache(store: Store) -> None:
    """받아 본 판정서 보관·조회."""
    store.save_jilbyeong([{"accnum": "240020210001542", "kinda": "인정", "kindb": "주방장 및 조리사",
                           "kindc": "뇌혈관질환", "title": "중식요리점", "noncontent": "주문 ..."}])
    row = store.get_jilbyeong(" 240020210001542 ")
    assert row is not None and row["kinda"] == "인정"
    assert store.get_jilbyeong("1") is None


def test_review_decision_cache_is_separate(store: Store) -> None:
    """심사결정서는 판정서와 따로 보관된다(같은 번호여도 섞이지 않음)."""
    store.save_cases("simsa", [{"accnum": "20170006029", "kinda": "기각", "kindb": "최초요양",
                                "kindc": "법리해석", "title": "진폐 요양급여 등 부지급 처분 취소 청구",
                                "noncontent": "청구인의 심사청구를 기각한다."}])
    assert store.get_case("simsa", "20170006029")["kindb"] == "최초요양"
    assert store.get_case("jilbyeong", "20170006029") is None
    with pytest.raises(ValueError):
        store.get_case("precedent; DROP TABLE meta", "1")


def test_forbidden_api_gives_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """활용신청하지 않은 API(403)는 재시도 없이 '활용신청 확인' 안내를 낸다."""
    import urllib.error
    import urllib.request

    import api_client

    calls = []

    def fake_urlopen(url: str, timeout: int = 0) -> None:
        calls.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ComwelApiError, match="활용신청"):
        api_client.ComwelClient("TESTKEY").case_codes("simsa", "kinda")
    assert len(calls) == 1


class FakeClient:
    """판례 API 흉내(쪽마다 정해진 건수)."""

    def __init__(self, total: int, deliver: int) -> None:
        """total=API가 알려 주는 총건수, deliver=실제로 돌려줄 건수."""
        self.total, self.deliver = total, deliver

    def precedent_page(self, page: int, size: int) -> tuple[int, list[dict[str, str]]]:
        """한 쪽 분량."""
        start = (page - 1) * size
        n = max(0, min(size, self.deliver - start))
        return self.total, [{"accnum": f"{start + i}", "noncontent": "본문"} for i in range(n)]


def test_sync_replaces_all(store: Store) -> None:
    """전체 갱신: 2,500건 → 3쪽 받아 통째로 교체."""
    info = sync_precedents(FakeClient(2500, 2500), store)
    assert info["count"] == 2500 and store.precedent_count() == 2500
    assert store.get_meta("precedent_sync")["api_total"] == 2500


def test_sync_keeps_old_data_when_incomplete(store: Store) -> None:
    """덜 받으면 기존 보관본을 지키고 오류."""
    with pytest.raises(ComwelApiError):
        sync_precedents(FakeClient(2500, 2400), store)
    assert store.precedent_count() == 3
