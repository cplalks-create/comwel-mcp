# -*- coding: utf-8 -*-
"""PC 보관용 SQLite 저장소.

- precedent: 산재 판례 판결문 전체(API에 검색어 기능이 없어 통째로 내려받아 검색)
- jilbyeong:  검색하면서 받아 본 질병판정서(API에 사건번호 조회 기능이 없어, 원문 열람·인용 대조용으로 보관)
- meta:       판례 내려받은 날짜·건수, 분류 코드 목록 등
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from search import compact

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS precedent (
    id INTEGER PRIMARY KEY,
    accnum TEXT NOT NULL,
    courtname TEXT,
    title TEXT,
    kinda TEXT,
    kindb TEXT,
    kindc TEXT,
    content TEXT,
    compact TEXT
);
CREATE INDEX IF NOT EXISTS idx_precedent_accnum ON precedent(accnum);
CREATE TABLE IF NOT EXISTS jilbyeong (
    accnum TEXT PRIMARY KEY,
    kinda TEXT,
    kindb TEXT,
    kindc TEXT,
    title TEXT,
    content TEXT,
    compact TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_text() -> str:
    """현재 시각(YYYY. M. D. HH:MM 형식)."""
    n = datetime.now()
    return f"{n.year}. {n.month}. {n.day}. {n:%H:%M}"


class Store:
    """SQLite 저장소."""

    def __init__(self, path: str | Path | None = None) -> None:
        """DB 파일을 열고 표를 만든다."""
        if path is None:
            data_dir = Path(os.environ.get("COMWEL_MCP_DATA", DEFAULT_DATA_DIR))
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "comwel.sqlite"
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── meta ──────────────────────────────────────────────
    def get_meta(self, key: str, default: object = None) -> object:
        """meta 값(JSON) 읽기."""
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value: object) -> None:
        """meta 값(JSON) 쓰기."""
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    # ── 판례 ──────────────────────────────────────────────
    def precedent_count(self) -> int:
        """보관 중인 판례 건수."""
        return int(self.db.execute("SELECT COUNT(*) FROM precedent").fetchone()[0])

    def replace_precedents(self, rows: Iterable[dict[str, str]]) -> int:
        """판례 전체를 새 자료로 바꾼다(한 번에 바꿔서, 중간에 실패해도 기존 자료는 남음)."""
        cur = self.db.cursor()
        try:
            cur.execute("BEGIN")
            cur.execute("DELETE FROM precedent")
            n = 0
            for r in rows:
                content = r.get("noncontent", "")
                cur.execute(
                    "INSERT INTO precedent(accnum, courtname, title, kinda, kindb, kindc, content, compact)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (r.get("accnum", ""), r.get("courtname", ""), r.get("title", ""), r.get("kinda", ""),
                     r.get("kindb", ""), r.get("kindc", ""), content, compact(content)),
                )
                n += 1
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return n

    def search_precedents(self, includes: list[str], excludes: list[str], kinda: str = "",
                          kindb: str = "", kindc: str = "", court: str = "", title: str = "",
                          offset: int = 0, limit: int = 10) -> tuple[int, list[sqlite3.Row]]:
        """판례 검색(본문 공백 무시 포함/제외 + 분류 조건). (총건수, 결과)."""
        where: list[str] = []
        args: list[object] = []
        for t in includes:
            where.append("instr(compact, ?) > 0")
            args.append(compact(t))
        for t in excludes:
            where.append("instr(compact, ?) = 0")
            args.append(compact(t))
        for col, val in (("kinda", kinda), ("kindb", kindb), ("kindc", kindc)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if court:
            where.append("instr(courtname, ?) > 0")
            args.append(court)
        if title:
            where.append("instr(title, ?) > 0")
            args.append(title)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = int(self.db.execute(f"SELECT COUNT(*) FROM precedent{clause}", args).fetchone()[0])
        rows = self.db.execute(
            f"SELECT * FROM precedent{clause} ORDER BY id LIMIT ? OFFSET ?", [*args, limit, offset]
        ).fetchall()
        return total, rows

    def get_precedents(self, accnum: str) -> list[sqlite3.Row]:
        """사건번호로 판례 찾기(공백 무시, 같은 번호가 여럿이면 모두)."""
        key = compact(accnum)
        rows = self.db.execute("SELECT * FROM precedent WHERE accnum = ?", (accnum.strip(),)).fetchall()
        if rows:
            return rows
        # '(창원)2018누10708' 처럼 앞에 지원명이 붙은 번호도 찾도록 부분 일치로 한 번 더
        return [r for r in self.db.execute(
            "SELECT * FROM precedent WHERE instr(replace(accnum, ' ', ''), ?) > 0", (key,)
        ).fetchall()]

    # ── 질병판정서 ─────────────────────────────────────────
    def save_jilbyeong(self, rows: Iterable[dict[str, str]]) -> None:
        """받아 본 질병판정서를 보관(같은 사건번호는 새로 덮어씀)."""
        stamp = now_text()
        self.db.executemany(
            "INSERT OR REPLACE INTO jilbyeong(accnum, kinda, kindb, kindc, title, content, compact, fetched_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            [(r.get("accnum", ""), r.get("kinda", ""), r.get("kindb", ""), r.get("kindc", ""),
              r.get("title", ""), r.get("noncontent", ""), compact(r.get("noncontent", "")), stamp)
             for r in rows if r.get("accnum")],
        )
        self.db.commit()

    def get_jilbyeong(self, accnum: str) -> sqlite3.Row | None:
        """사건번호로 보관된 질병판정서 찾기."""
        return self.db.execute("SELECT * FROM jilbyeong WHERE accnum = ?",
                               (compact(accnum),)).fetchone()

    # ── 분류 코드 캐시 ──────────────────────────────────────
    def cached_codes(self, key: str, loader: Callable[[], list[str]]) -> list[str]:
        """분류 코드 목록을 하루 동안 보관해 두고 쓴다."""
        cached = self.get_meta(key)
        today = datetime.now().strftime("%Y-%m-%d")
        if isinstance(cached, dict) and cached.get("date") == today:
            return list(cached.get("codes", []))
        codes = loader()
        self.set_meta(key, {"date": today, "codes": codes})
        return codes
