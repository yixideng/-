"""把解析出的词条 JSONL 压成可检索的 SQLite 库（含 FTS5 全文索引）。

产出 data/processed/dict.sqlite，包含：
  entries      —— 词条主表（每来源一条）
  entries_fts  —— FTS5 全文索引（headword + full_text），供模糊/全文检索
  alt_map      —— 异体 -> 规范词头 映射，使「亦作」形也能查到
并在 headword 上建普通索引，支持精确查询与前缀（LIKE 'xxx%'）查询。

用法：
    python pipeline/build_index.py data/processed/dict.jsonl \
        --out data/processed/dict.sqlite
"""
import argparse
import json
import sqlite3
from pathlib import Path


def build(jsonl: Path, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    cur = con.cursor()
    cur.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE entries(
            id INTEGER PRIMARY KEY,
            headword TEXT NOT NULL,
            headword_raw TEXT,
            source TEXT,
            page TEXT,
            pos TEXT,
            tags TEXT,          -- JSON 数组
            alt_forms TEXT,     -- JSON 数组
            senses TEXT,        -- JSON 数组
            bo_examples TEXT,   -- JSON 数组
            full_text TEXT
        );
        CREATE TABLE alt_map(alt TEXT, headword TEXT);
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            headword, full_text, content=''
        );
    """)

    n = 0
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            cur.execute(
                "INSERT INTO entries(headword,headword_raw,source,page,pos,"
                "tags,alt_forms,senses,bo_examples,full_text) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    e["headword"], e.get("headword_raw", ""), e.get("source", ""),
                    e.get("page", ""), e.get("pos", ""),
                    json.dumps(e.get("tags", []), ensure_ascii=False),
                    json.dumps(e.get("alt_forms", []), ensure_ascii=False),
                    json.dumps(e.get("senses", []), ensure_ascii=False),
                    json.dumps(e.get("bo_examples", []), ensure_ascii=False),
                    e.get("full_text", ""),
                ),
            )
            rowid = cur.lastrowid
            cur.execute(
                "INSERT INTO entries_fts(rowid,headword,full_text) VALUES(?,?,?)",
                (rowid, e["headword"], e.get("full_text", "")),
            )
            for alt in e.get("alt_forms", []):
                cur.execute("INSERT INTO alt_map(alt,headword) VALUES(?,?)",
                            (alt, e["headword"]))
            n += 1

    cur.executescript("""
        CREATE INDEX idx_headword ON entries(headword);
        CREATE INDEX idx_alt ON alt_map(alt);
    """)
    con.commit()
    con.close()
    print(f"入库 {n} 条 -> {out}（{out.stat().st_size/1024/1024:.1f} MB）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/processed/dict.sqlite"))
    args = ap.parse_args()
    build(args.input, args.out)


if __name__ == "__main__":
    main()
