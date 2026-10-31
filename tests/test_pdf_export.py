# -*- coding: utf-8 -*-
"""PDF 저장 모듈 테스트(공단 사이트 접속 없음. 브라우저가 있으면 원문 출력본 PDF 실제 생성까지)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pdf_export  # noqa: E402

JIL_HTML = """<table><col style="width: 20%;" /><col style="width: 80%;" />
<tr> <th scope="row">판정번호</th> <td>2019 판정 제 2667호</td> </tr>
<!-- <tr> --> <!-- <th scope="row">업종</th> --> <!-- </tr> -->
<tr> <th scope="row">판정일</th> <td>2019.12.26</td> </tr></table>"""

PAN_HTML = """<div id="wrap" class="printDiv"> <div class="contTopArea"> <h1>전주지방법원</h1> <h2>제2행정부</h2>
<h3> [2014구합2765 ] </h3> </div> <div class="contMd"> <div class="info">
<ul> <li class="item1">피 고</li> <li class="item2"> 근로복지공단 </li> </ul>
<ul> <li class="item1">변론종결</li> <li class="item2">2017. 08. 17</li> </ul>
<ul> <li class="item1">판결선고</li> <li class="item2">2017. 09. 28</li> </ul> </div>"""


def test_parse_jil_meta() -> None:
    """판정서 화면에서 판정번호·판정일."""
    assert pdf_export.parse_jil_meta(JIL_HTML) == {"official_no": "2019 판정 제 2667호", "decided_on": "2019.12.26"}


def test_parse_pan_meta() -> None:
    """판례 화면에서 재판부·변론종결·선고일."""
    assert pdf_export.parse_pan_meta(PAN_HTML) == {
        "division": "전주지방법원 제2행정부", "closed_on": "2017. 08. 17", "decided_on": "2017. 09. 28"}


def test_parse_missing_fields_are_blank() -> None:
    """항목이 없으면 빈 값(짐작하지 않음)."""
    assert pdf_export.parse_jil_meta("<html></html>") == {"official_no": "", "decided_on": ""}


def test_urls_are_encoded() -> None:
    """판례 사이트 번호는 '사건번호_법원명'을 주소에 맞게 바꾼다."""
    view, prt = pdf_export.pan_urls("2014구합2765", "전주지방법원")
    assert view.startswith("https://sanjaecase.comwel.or.kr/service/dataView?id=2014%EA%B5%AC")
    assert "dataViewPrint" in prt and "_%EC%A0%84%EC%A3%BC" in prt
    assert pdf_export.jil_urls("540020190002667")[1].endswith("dataViewPrint?id=540020190002667")


def test_safe_name_and_unique_path(tmp_path: Path) -> None:
    """파일 이름 정리와 중복 회피."""
    name = pdf_export.safe_name("질병판정서", "2019 판정 제 2667호", "인정", "‘우측 퇴행성 슬관절염’/좌측?")
    assert name == "질병판정서_2019판정제2667호_인정_우측퇴행성슬관절염좌측"
    p1 = pdf_export.unique_path(tmp_path, "a")
    p1.write_bytes(b"x")
    assert pdf_export.unique_path(tmp_path, "a").name == "a_2.pdf"


def test_first_disease() -> None:
    """주문의 첫 상병명."""
    order = "주문 신청인이 요양급여 신청한 상병 ‘우측 퇴행성 슬관절염’,‘좌측 퇴행성 슬관절염’은 …"
    assert pdf_export.first_disease(order) == "우측 퇴행성 슬관절염"
    assert pdf_export.first_disease("상병명 없음") == ""


def test_request_headers_are_ascii() -> None:
    """HTTP 헤더에 한글이 들어가면 접속 자체가 실패하므로 영문만 쓴다."""
    for v in pdf_export.UA.values():
        v.encode("latin-1")


def test_browser_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수로 브라우저 경로를 지정할 수 있다."""
    fake = tmp_path / "mybrowser.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv(pdf_export.BROWSER_ENV, str(fake))
    assert pdf_export.find_browser() == str(fake)


def test_no_browser_gives_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """브라우저가 없으면 설치·경로 지정 안내."""
    monkeypatch.setattr(pdf_export, "find_browser", lambda: None)
    with pytest.raises(pdf_export.PdfError, match="Edge 또는 Chrome"):
        pdf_export.print_to_pdf("https://example.invalid", tmp_path / "x.pdf")


@pytest.mark.skipif(pdf_export.find_browser() is None, reason="이 PC에 Edge/Chrome 없음")
def test_text_pdf_real(tmp_path: Path) -> None:
    """원문 출력본 PDF 실제 생성: 한글·출처 표기·공식 문서 아님 안내가 들어간다."""
    out = tmp_path / "simsa.pdf"
    pdf_export.text_pdf("산재보험 심사결정서(원문 출력본)", [("심사사건번호", "20170006202"), ("출처", "공공데이터포털")],
                        "주문\n원처분기관이 2017. 8. 4. 청구인에게 행한 최초요양 불승인 처분을 취소한다.", out, "바닥글")
    assert out.read_bytes()[:5] == b"%PDF-"
    assert pdf_export.pdf_contains(out, "최초요양 불승인 처분을 취소한다") is True
    assert pdf_export.pdf_contains(out, "공식 문서가 아닙니다") is True
