"""命令行查词工具（也是 Agent 端 lookup_dict 的参考实现）。

查询顺序：精确词头 -> 异体映射 -> 前缀匹配。都没有再退回 FTS 全文检索。
所有查询词先经 normalize.lookup_key 归一（NFC + 去 shad/tsheg）。

用法：
    python pipeline/lookup.py བྱང་ཆུབ་སེམས
    python pipeline/lookup.py --db data/processed/dict.sqlite ཆོས
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import lookup_key  # noqa: E402


def lookup(db: Path, word: str, limit: int = 10):
    key = lookup_key(word)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def rows(sql, args):
        return [dict(r) for r in cur.execute(sql, args).fetchall()]

    hits = rows("SELECT * FROM entries WHERE headword=? ORDER BY source", (key,))
    kind = "精确"
    if not hits:
        alts = rows("SELECT headword FROM alt_map WHERE alt=?", (key,))
        if alts:
            hw = alts[0]["headword"]
            hits = rows("SELECT * FROM entries WHERE headword=?", (hw,))
            kind = f"异体->{hw}"
    if not hits:
        hits = rows("SELECT * FROM entries WHERE headword LIKE ? LIMIT ?",
                    (key + "%", limit))
        kind = "前缀"
    con.close()
    return kind, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("word")
    ap.add_argument("--db", type=Path, default=Path("data/processed/dict.sqlite"))
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    kind, hits = lookup(args.db, args.word, args.limit)
    print(f"查询「{args.word}」 归一键=「{lookup_key(args.word)}」 匹配方式={kind} 命中{len(hits)}条")
    for h in hits:
        tags = json.loads(h["tags"])
        senses = json.loads(h["senses"])
        head = f"【{h['headword']}】{h['source']}"
        if h["page"]:
            head += f" p.{h['page']}"
        if h["pos"]:
            head += f" 〔{h['pos']}〕"
        if tags:
            head += f" 标签{tags}"
        print(head)
        for i, s in enumerate(senses, 1):
            print(f"   {i}. {s}")


if __name__ == "__main__":
    main()
