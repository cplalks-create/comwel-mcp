# -*- coding: utf-8 -*-
"""검색어 해석·발췌·인용 대조 단위 테스트(인터넷 불필요)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from search import compact, matches, parse_query, snippets, verify_quote  # noqa: E402

ORIGINAL = (
    "이 법원이 이 사건에 관하여 설시할 이유는 아래와 같이 추가하는 외에는 제1심판결의 이유 부분 기재와 같으므로, "
    "행정소송법 제8조 제2항, \n민사소송법 제420조 본문에\n의하여 이를 그대로 인용한다.\n"
    "그러나 제1심의 각 감정의가 “이 사건 상병은 업무로 인한 급성 스트레스로 인한 뇌출혈로 판단하기 어렵고”라고 감정하였다."
)


def test_parse_query_and_exclude_and_phrase() -> None:
    """AND·제외어·따옴표 구절을 나눈다."""
    inc, exc = parse_query('조리흄 폐암 -흡연 "업무상 재해"')
    assert inc == ["조리흄", "폐암", "업무상 재해"]
    assert exc == ["흡연"]


def test_parse_query_smart_quotes_and_broken_quote() -> None:
    """둥근 따옴표와 짝 안 맞는 따옴표도 처리한다."""
    assert parse_query("“업무상 재해” 과로")[0] == ["업무상 재해", "과로"]
    assert parse_query('"업무상 재해 과로')[0] == ["업무상", "재해", "과로"]


def test_parse_query_empty() -> None:
    """빈 검색어."""
    assert parse_query("") == ([], [])
    assert parse_query("  -  ") == (["-"], [])


def test_matches_ignores_whitespace() -> None:
    """줄바꿈으로 끊긴 구절도 찾는다."""
    body = compact(ORIGINAL)
    assert matches(body, ["제2항, 민사소송법"], [])
    assert matches(body, ["뇌출혈", "감정의"], [])
    assert not matches(body, ["뇌출혈"], ["감정의"])
    assert not matches(body, ["폐암"], [])


def test_verify_quote_exact_match_with_whitespace_difference() -> None:
    """공백·줄바꿈만 다른 인용은 일치."""
    r = verify_quote(ORIGINAL, "행정소송법 제8조 제2항, 민사소송법 제420조 본문에 의하여")
    assert r["matched"] is True
    assert "행정소송법" in r["context"]


def test_verify_quote_detects_changed_word() -> None:
    """한 글자라도 바뀌면 불일치, 어긋난 위치를 알려 준다."""
    r = verify_quote(ORIGINAL, "행정소송법 제8조 제3항, 민사소송법")
    assert r["matched"] is False
    assert r["matched_prefix"] == len(compact("행정소송법 제8조 제"))
    assert r["mismatch_at"].startswith("3항")


def test_verify_quote_quote_marks_are_strict() -> None:
    """따옴표 모양도 원문 그대로여야 한다(곧은 따옴표로 바꾸면 불일치)."""
    assert verify_quote(ORIGINAL, "감정의가 “이 사건 상병은")["matched"] is True
    assert verify_quote(ORIGINAL, '감정의가 "이 사건 상병은')["matched"] is False


def test_verify_quote_empty() -> None:
    """빈 인용문은 불일치."""
    assert verify_quote(ORIGINAL, "   ")["matched"] is False


def test_snippets_around_term_across_linebreak() -> None:
    """줄바꿈을 사이에 둔 검색어 주변을 발췌한다."""
    out = snippets(ORIGINAL, ["본문에 의하여"], width=10)
    assert len(out) == 1
    assert "본문에 의하여" in out[0]
    assert out[0].startswith("…") and out[0].endswith("…")


def test_snippets_without_terms_returns_head() -> None:
    """검색어가 없으면 앞부분."""
    out = snippets("짧은 본문", [])
    assert out == ["짧은 본문"]
