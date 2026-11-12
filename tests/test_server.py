# -*- coding: utf-8 -*-
"""서버 도구 테스트(가짜 공단 API·임시 DB, 인터넷 불필요)."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# server 모듈은 불러올 때 보관본을 연다. 실제 보관본을 건드리지 않도록 임시 폴더를 먼저 지정한다.
os.environ["COMWEL_MCP_DATA"] = tempfile.mkdtemp(prefix="comwel_test_")

import pdf_export  # noqa: E402
import server  # noqa: E402
from store import Store  # noqa: E402


def doc(no: str, body: str, kinda: str = "인정", title: str = "건축건설공사") -> dict[str, str]:
    """가짜 판정서 한 건."""
    return {"accnum": no, "kinda": kinda, "kindb": "건설관련 기능 종사자", "kindc": "근골격계질환(척추질환 제외)",
            "title": title, "noncontent": body}


DOCS = [
    doc("1001", "형틀목수로 근무하며 슬관절 통증. 쪼그려 앉기 반복."),
    doc("1002", "형틀목수로 근무하며 어깨 통증."),
    doc("1003", "조리사로 근무하며 슬관절 통증.", title="음식 및 숙박업"),
    doc("1004", "형틀목수이나 흡연력이 있고 슬관절 통증.", kinda="불인정"),
]


class FakeClient:
    """공단 결정서 API 흉내: cq(본문 한 낱말)·tq(제목)·kinda 조건으로 거른다."""

    def __init__(self, docs: list[dict[str, str]], inflate_total: int = 0) -> None:
        """inflate_total 을 주면 총건수를 부풀려 '일부만 훑음' 상황을 만든다."""
        self.docs, self.inflate_total, self.calls = docs, inflate_total, []

    def _filter(self, kinda: str = "", kindb: str = "", kindc: str = "", tq: str = "", cq: str = "") -> list[dict]:
        return [d for d in self.docs
                if (not cq or cq in d["noncontent"]) and (not tq or tq in d["title"]) and (not kinda or d["kinda"] == kinda)]

    def case_count(self, svc: str, **kw: str) -> int:
        """조건에 맞는 건수."""
        self.calls.append(("count", kw))
        return len(self._filter(**kw))

    def case_page(self, svc: str, page: int, size: int, **kw: str) -> tuple[int, list[dict]]:
        """한 쪽."""
        self.calls.append(("page", kw))
        rows = self._filter(**kw)
        return (self.inflate_total or len(rows)), rows[(page - 1) * size: page * size]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """임시 보관본과 가짜 API를 서버에 끼운다."""
    client = FakeClient(DOCS)
    monkeypatch.setattr(server, "_store", Store(tmp_path / "t.sqlite"))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_scan_cache", type(server._scan_cache)())
    monkeypatch.setenv("COMWEL_UPDATE_CHECK", "0")
    return client


def test_tools_return_plain_text_and_have_hints() -> None:
    """도구 결과는 일반 글이고, 검색 도구는 읽기 전용·저장 도구는 쓰기로 표시된다."""
    import asyncio

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert len(tools) == 12
    for name, tool in tools.items():
        assert tool.output_schema is None, name            # {"result": ...} 로 싸지 않음
        assert tool.annotations.read_only_hint is (name not in ("save_pdf", "update_precedents")), name
        assert tool.title


def test_single_keyword_goes_straight_to_server(env: FakeClient) -> None:
    """낱말 하나는 공단 서버 검색 한 번으로 끝낸다."""
    out = server.search_disease_rulings(keywords="어깨")
    assert "총 1건" in out and "판정위 사건번호 1002" in out
    assert [c[0] for c in env.calls] == ["page"]


def test_multi_keyword_scans_rarest_term_and_filters(env: FakeClient) -> None:
    """여러 낱말·제외어는 가장 드문 낱말로 받아 PC에서 거른다."""
    out = server.search_disease_rulings(keywords="형틀목수 슬관절 -흡연", result="")
    assert "총 1건" in out and "판정위 사건번호 1001" in out and "1004" not in out
    pages = [c[1] for c in env.calls if c[0] == "page"]
    assert pages and all(p.get("cq") in ("형틀목수", "슬관절") for p in pages)
    # 검색해 본 판정서는 보관되어 전문을 열 수 있다
    assert "쪼그려 앉기 반복" in server.get_disease_ruling("1001")


def test_title_filter_with_keyword(env: FakeClient) -> None:
    """업종(제목) 조건과 본문 낱말을 함께 쓴다."""
    out = server.search_disease_rulings(keywords="슬관절", industry="음식")
    assert "총 1건" in out and "1003" in out


def test_partial_scan_is_flagged(env: FakeClient) -> None:
    """후보가 너무 많아 다 훑지 못하면 그 사실을 알린다."""
    env.inflate_total = 99999
    out = server.search_disease_rulings(keywords="형틀목수 슬관절")
    assert "훑었습니다" in out


def test_get_uncached_ruling_guides_to_search(env: FakeClient) -> None:
    """검색해 본 적 없는 번호는 지어내지 않고 검색을 안내한다."""
    out = server.get_disease_ruling("9999")
    assert "보관본에 없습니다" in out and "search_disease_rulings" in out


def test_verify_quote_paths(env: FakeClient) -> None:
    """인용 대조: 일치·불일치·문장부호 모양만 다름·원문 없음."""
    server._store.save_cases("simsa", [{"accnum": "20170006202", "kinda": "취소", "kindb": "최초요양",
                                        "kindc": "근로자 여부", "title": "취소 청구",
                                        "noncontent": "원처분기관이 행한 ‘최초요양 불승인’ 처분을 취소한다."}])
    assert "[일치]" in server.verify_quote("심사결정서", "20170006202", "처분을 취소한다.")
    assert "[불일치]" in server.verify_quote("심사결정서", "20170006202", "처분을 기각한다.")
    near = server.verify_quote("심사결정서", "20170006202", "원처분기관이 행한 '최초요양 불승인' 처분")
    assert "문장부호 모양만 다름" in near and "‘최초요양 불승인’" in near
    assert "[확인 불가]" in server.verify_quote("심사결정서", "20179999999", "아무 문장이나 넣어 봄")


def test_precedent_tools_without_archive(env: FakeClient) -> None:
    """판례 보관본이 없으면 검색 결과를 지어내지 않고 상태를 알린다."""
    assert "보관본" in server.search_precedents(keywords="폐암")
    assert "보관본" in server.get_precedent("2014구합2765")


def test_save_pdf_limits_and_empty(env: FakeClient) -> None:
    """PDF 저장: 빈 목록·건수 초과는 저장하지 않는다."""
    assert "사건번호를 넣어" in server.save_pdf("판정서", ["  "])
    assert "최대 20건" in server.save_pdf("판정서", [str(i) for i in range(21)])


def test_save_pdf_site_down_is_not_reported_as_missing(env: FakeClient, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """공단 사이트 접속 실패는 '없는 번호'가 아니라 접속 실패로 알리고, 원문 출력본으로 대신하지 않는다."""
    server.search_disease_rulings(keywords="어깨")     # 1002 보관

    def down(case_number: str) -> dict:
        raise pdf_export.SiteUnavailable("공단 사이트 접속 실패: 시간 초과")

    monkeypatch.setattr(pdf_export, "jil_meta", down)
    out = server.save_pdf("판정서", ["1002"], folder=str(tmp_path / "out"))
    assert "[실패]" in out and "접속 실패" in out and "저장 0건" in out
    assert not list((tmp_path / "out").glob("*.pdf"))


def test_save_pdf_stops_when_no_browser(env: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """브라우저가 없으면 첫 건에서 멈춘다(나머지도 같은 이유로 실패하므로)."""
    server._store.save_cases("simsa", [dict(doc("20170000001", "본문"), kinda="기각"),
                                       dict(doc("20170000002", "본문"), kinda="기각")])
    monkeypatch.setattr(pdf_export, "find_browser", lambda: None)
    monkeypatch.setattr(pdf_export, "pause", lambda: None)
    out = server.save_pdf("심사결정서", ["20170000001", "20170000002"], folder=str(tmp_path / "out"))
    assert out.count("[실패]") == 1 and "Edge 또는 Chrome" in out
