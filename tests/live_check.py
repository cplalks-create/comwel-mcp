# -*- coding: utf-8 -*-
"""실제 공단 서버·실제 MCP 연결로 도구를 모두 불러 보는 점검 스크립트(인증키·인터넷 필요).

실행:
    py -X utf8 tests/live_check.py
"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "src" / "server.py"

CALLS = [
    ("search_disease_rulings", {"keywords": "조리흄", "size": 2}),
    ("search_disease_rulings", {"keywords": "조리흄 폐암", "result": "인정", "size": 2}),
    ("search_disease_rulings", {"industry": "학교", "disease": "악성신생물(직업성 암 포함)", "size": 1}),
    ("get_disease_ruling", {"case_number": "__FIRST_JIL__"}),
    ("search_precedents", {"keywords": "조리흄 폐암", "size": 3}),
    ("get_precedent", {"case_number": "2018누10708"}),
    ("verify_quote", {"source": "판례", "case_number": "2018누10708",
                      "quote": "원고의 항소를 기각한다. 2. 항소비용은 원고가 부담한다."}),
    ("verify_quote", {"source": "판례", "case_number": "2018누10708",
                      "quote": "원고의 항소를 인용한다."}),
    ("verify_quote", {"source": "판정서", "case_number": "__FIRST_JIL__",
                      "quote": "__JIL_QUOTE__"}),
    ("search_review_decisions", {"keywords": "출퇴근", "result": "취소", "size": 2}),
    ("search_review_decisions", {"keywords": "폐암 석면", "size": 2}),
    ("search_review_decisions", {"case_name": "평균임금", "issue": "법리해석", "size": 1}),
    ("get_review_decision", {"case_number": "__FIRST_SIMSA__"}),
    ("verify_quote", {"source": "심사결정서", "case_number": "__FIRST_SIMSA__",
                      "quote": "청구인의 심사청구를 기각한다."}),
    ("list_codes", {"source": "판례"}),
    ("list_codes", {"source": "판정서"}),
    ("list_codes", {"source": "심사결정서"}),
]


def text_of(result) -> str:
    """도구 결과 본문."""
    return "\n".join(getattr(c, "text", "") for c in result.content)


async def main() -> int:
    """서버를 띄워 도구를 차례로 부른다."""
    params = StdioServerParameters(command=sys.executable, args=["-X", "utf8", str(SERVER)])
    first_jil, jil_quote, first_simsa = "", "", ""
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("도구 목록:", [t.name for t in tools.tools])
            for name, args in CALLS:
                swap = {"__FIRST_JIL__": first_jil, "__JIL_QUOTE__": jil_quote, "__FIRST_SIMSA__": first_simsa}
                args = {k: swap.get(v, v) if isinstance(v, str) else v for k, v in args.items()}
                res = await session.call_tool(name, args)
                out = text_of(res)
                import re
                if name == "search_disease_rulings" and not first_jil:
                    first_jil = re.search(r"판정위 사건번호 (\d+)", out).group(1)
                if name == "search_review_decisions" and not first_simsa:
                    first_simsa = re.search(r"심사사건번호 (\d+)", out).group(1)
                if name == "get_disease_ruling":
                    body = out.split("\n\n", 1)[1]
                    jil_quote = body.strip().splitlines()[1][:60]
                print(f"\n{'=' * 70}\n▶ {name} {args}\n{'-' * 70}\n{out[:1200]}"
                      + ("\n…(생략)" if len(out) > 1200 else ""))
                if res.is_error:
                    print("!! 오류 응답")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
