# -*- coding: utf-8 -*-
"""판정서·판결문·심사결정서를 근거자료용 PDF로 저장한다.

- 질병판정서·판례: 근로복지공단 공개 사이트의 [프린트] 화면을 PC의 Edge/Chrome으로 '화면 없이' 인쇄한다.
  (공단 양식 그대로이며, 모든 쪽 아래에 출력 일시·원본 주소·쪽 번호가 브라우저에 의해 자동으로 찍힌다)
- 심사결정서: 건별 공개 화면이 없어 공공데이터 API 원문을 그대로 옮긴 '원문 출력본'을 만든다.
- 공단 사이트에서 판정번호·판정일(판정서), 재판부·선고일(판례)도 읽어 온다(API에는 없는 정보).

Claude in Chrome 같은 확장 프로그램은 필요 없다. 브라우저 위치는 자동으로 찾고,
못 찾으면 환경변수 COMWEL_PDF_BROWSER 에 브라우저 실행 파일 경로를 넣으면 된다.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

JIL_SITE = "https://jilbyungcase.comwel.or.kr/service/"
PAN_SITE = "https://sanjaecase.comwel.or.kr/service/"
BROWSER_ENV = "COMWEL_PDF_BROWSER"
DEFAULT_FOLDER = Path.home() / "Documents" / "comwel_PDF"
PRINT_TIMEOUT = 120
UA = {"User-Agent": "Mozilla/5.0 (compatible; comwel-mcp)"}  # HTTP 헤더는 영문만 가능


class PdfError(Exception):
    """PDF 저장 실패."""


# ── 공단 사이트 주소·정보 ──────────────────────────────────────
def jil_urls(case_number: str) -> tuple[str, str]:
    """질병판정서 (화면 주소, 인쇄 주소)."""
    q = urllib.parse.quote(case_number.strip())
    return f"{JIL_SITE}dataView?id={q}", f"{JIL_SITE}dataViewPrint?id={q}"


def pan_urls(case_number: str, court: str) -> tuple[str, str]:
    """판례 (화면 주소, 인쇄 주소). 사이트 번호는 '사건번호_법원명' 형식."""
    q = urllib.parse.quote(f"{case_number.strip()}_{court.strip()}")
    return f"{PAN_SITE}dataView?id={q}", f"{PAN_SITE}dataViewPrint?id={q}"


def _fetch(url: str) -> str | None:
    """화면 HTML. 없는 번호면(공단 서버 400/404) None."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return None
        raise PdfError(f"공단 사이트 접속 실패(HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise PdfError(f"공단 사이트 접속 실패: {exc}") from exc


def _cell(page: str, label: str) -> str:
    """<th>라벨</th><td>값</td> 또는 <li class=item1>라벨</li><li class=item2>값</li> 형식의 값."""
    for pat in (rf"<th[^>]*>\s*{label}\s*</th>\s*<td[^>]*>(.*?)</td>",
                rf'class="item1">\s*{label}\s*</li>\s*<li class="item2">(.*?)</li>'):
        m = re.search(pat, page, re.S)
        if m:
            return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
    return ""


def parse_jil_meta(page: str) -> dict[str, str]:
    """판정서 화면에서 판정번호·판정일."""
    return {"official_no": _cell(page, "판정번호"), "decided_on": _cell(page, "판정일")}


def parse_pan_meta(page: str) -> dict[str, str]:
    """판례 화면에서 재판부·변론종결·선고일."""
    m = re.search(r'class="contTopArea">\s*<h1>(.*?)</h1>\s*<h2>(.*?)</h2>', page, re.S)
    division = " ".join(x.strip() for x in m.groups()) if m else ""
    return {"division": division, "closed_on": _cell(page, "변론종결"), "decided_on": _cell(page, "판결선고")}


def jil_meta(case_number: str) -> dict[str, str] | None:
    """공단 사이트에서 판정서 정보. 없는 번호면 None."""
    view, _ = jil_urls(case_number)
    page = _fetch(view)
    if page is None or "판정번호" not in page:
        return None
    return {**parse_jil_meta(page), "url": view}


def pan_meta(case_number: str, court: str) -> dict[str, str] | None:
    """공단 사이트에서 판례 정보. 없는 번호면 None."""
    view, _ = pan_urls(case_number, court)
    page = _fetch(view)
    if page is None or "판결선고" not in page and "주문" not in page:
        return None
    return {**parse_pan_meta(page), "url": view}


# ── 브라우저 ──────────────────────────────────────────────
def find_browser() -> str | None:
    """PC에 있는 Edge/Chrome 실행 파일."""
    env = os.environ.get(BROWSER_ENV, "").strip().strip('"')
    if env and Path(env).exists():
        return env
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe") if local else "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def print_to_pdf(target: str, out_path: Path, header_footer: bool = True) -> None:
    """브라우저를 화면 없이 실행해 target(주소 또는 파일)을 PDF로 인쇄한다."""
    browser = find_browser()
    if not browser:
        raise PdfError("PDF로 인쇄할 Edge 또는 Chrome을 찾지 못했습니다. "
                       f"브라우저를 설치하거나 환경변수 {BROWSER_ENV}에 실행 파일 경로를 넣어 주세요.")
    profile = tempfile.mkdtemp(prefix="comwel_pdf_")
    tmp_out = Path(profile) / "out.pdf"
    args = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}", f"--print-to-pdf={tmp_out}"]
    if not header_footer:
        args.append("--no-pdf-header-footer")
    args.append(target)
    try:
        subprocess.run(args, capture_output=True, timeout=PRINT_TIMEOUT,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not tmp_out.exists() or tmp_out.stat().st_size < 1000 or not tmp_out.read_bytes()[:5] == b"%PDF-":
            raise PdfError("브라우저가 PDF를 만들지 못했습니다.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_out), str(out_path))
    except subprocess.TimeoutExpired as exc:
        raise PdfError(f"PDF 인쇄가 {PRINT_TIMEOUT}초 안에 끝나지 않았습니다.") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def pdf_contains(path: Path, needle: str) -> bool | None:
    """PDF 첫 두 쪽에 needle이 있는지(pypdf가 없으면 None = 확인 생략)."""
    try:
        import pypdf
    except ImportError:
        return None
    try:
        reader = pypdf.PdfReader(str(path))
        text = "".join(p.extract_text() or "" for p in reader.pages[:2])
    except Exception:
        return None
    return re.sub(r"\s+", "", needle) in re.sub(r"\s+", "", text)


# ── 파일 이름 ─────────────────────────────────────────────
def safe_name(*parts: str, limit: int = 110) -> str:
    """파일 이름에 쓸 수 없는 글자를 빼고 이어 붙인다."""
    joined = "_".join(re.sub(r"\s+", "", p) for p in parts if p)
    joined = re.sub(r'[\\/:*?"<>|\'‘’“”\[\]]', "", joined)
    return joined[:limit].rstrip("._") or "comwel"


def unique_path(folder: Path, stem: str) -> Path:
    """같은 이름이 있으면 _2, _3 을 붙인다."""
    p = folder / f"{stem}.pdf"
    n = 2
    while p.exists():
        p = folder / f"{stem}_{n}.pdf"
        n += 1
    return p


def first_disease(order_text: str) -> str:
    """주문에서 첫 상병명(따옴표 안)."""
    m = re.search(r"[‘'“\"]([^’'”\"]{2,60})[’'”\"]", order_text or "")
    return m.group(1) if m else ""


def resolve_folder(folder: str) -> Path:
    """저장 폴더(빈 값이면 문서\\comwel_PDF)."""
    return Path(folder).expanduser() if folder.strip() else DEFAULT_FOLDER


# ── 원문 출력본(심사결정서 등) ──────────────────────────────
TEXT_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: A4; margin: 18mm 16mm 20mm 16mm; }}
body {{ font-family: 'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo','Noto Sans KR',sans-serif; font-size: 10.5pt; line-height: 1.6; color:#000; }}
h1 {{ font-size: 16pt; text-align:center; margin: 0 0 10px; letter-spacing: 2px; }}
table.meta {{ width:100%; border-collapse: collapse; margin: 8px 0 14px; font-size: 9.5pt; }}
table.meta th, table.meta td {{ border:1px solid #888; padding:4px 6px; text-align:left; vertical-align:top; }}
table.meta th {{ width: 20%; background:#f0f0f0; }}
.notice {{ border:1px solid #c00; color:#900; padding:6px 8px; font-size:9pt; margin-bottom:12px; }}
.body {{ white-space: pre-wrap; word-break: break-all; }}
.foot {{ position: fixed; bottom: -12mm; left: 0; right: 0; font-size: 8pt; color:#555; text-align:center; }}
</style></head><body>
<h1>{title}</h1>
<div class="notice">이 문서는 공공데이터포털 API로 받은 원문을 그대로 옮긴 출력본이며, 근로복지공단이 발급한 공식 문서가 아닙니다. 개인정보는 공단이 ○○ 등으로 가린 상태 그대로입니다.</div>
<table class="meta">{rows}</table>
<div class="body">{body}</div>
<div class="foot">{foot}</div>
</body></html>"""


def text_pdf(title: str, meta_rows: list[tuple[str, str]], body: str, out_path: Path, foot: str) -> None:
    """API 원문으로 '원문 출력본' PDF를 만든다."""
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in meta_rows)
    doc = TEXT_TEMPLATE.format(title=html.escape(title), rows=rows, body=html.escape(body.strip()),
                               foot=html.escape(foot))
    tmpdir = tempfile.mkdtemp(prefix="comwel_txt_")
    try:
        src = Path(tmpdir) / "doc.html"
        src.write_text(doc, encoding="utf-8")
        print_to_pdf(src.as_uri(), out_path, header_footer=False)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def now_text() -> str:
    """조회 일시 표기."""
    n = datetime.now()
    return f"{n.year}. {n.month}. {n.day}. {n:%H:%M}"


def pause() -> None:
    """여러 건을 받을 때 공단 사이트 부담을 줄이려고 잠깐 쉰다."""
    time.sleep(1.5)
