"""Agent 检索工具三件套：查词典 / 查术语表 / 查翻译记忆。

被 translator.py 调用；也可单独 import 使用。
所有输入藏文自动经 normalize 归一后再查。
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from normalize import lookup_key, nfc  # noqa: E402

DICT_DBS = [
    ("藏汉大辞典", ROOT / "data/processed/dict.sqlite"),
    ("格西曲扎", ROOT / "data/processed/gexi.sqlite"),
]
GLOSSARY = ROOT / "glossary/glossary.tsv"   # 人工修订的核心资产（进仓库）
TM_FILES = [
    ROOT / "data/processed/tm_gzhanstong_reviewed.jsonl",  # 用户校订·文风范本，优先
    ROOT / "data/processed/tm_gzhanstong_2.jsonl",         # 同上（2.0 论体）
    ROOT / "data/processed/tm_zhongguan.jsonl",
    ROOT / "data/processed/tm_baoxinglun.jsonl",
]

# 常见格助词/接续，剥离后重查（简单形态还原）
CASE_SUFFIXES = ["འི", "ར", "ས", "འམ", "འང", "ཀྱི", "གྱི", "གི", "ཡི",
                 "ཀྱིས", "གྱིས", "གིས", "ཡིས", "ཏུ", "དུ", "སུ", "ལ", "ན"]


def syllables(bo: str):
    return [s for s in re.split(r"[་།༎\s]+", nfc(bo)) if s]


# ---------- 词典 ----------

def _query_db(db: Path, key: str):
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT headword, source, page, pos, senses FROM entries WHERE headword=?",
        (key,)).fetchall()
    if not rows:
        alt = con.execute("SELECT headword FROM alt_map WHERE alt=?", (key,)).fetchone()
        if alt:
            rows = con.execute(
                "SELECT headword, source, page, pos, senses FROM entries WHERE headword=?",
                (alt[0],)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def lookup_dict(word: str, compact=True):
    """查两本词典。查不到时剥格助词重试。返回 [{headword,source,senses...}]"""
    key = lookup_key(word)
    results = []
    for _, db in DICT_DBS:
        results += _query_db(db, key)
    if not results:
        for suf in CASE_SUFFIXES:
            if key.endswith(suf) and len(key) > len(suf):
                stem = key[: -len(suf)].rstrip("་")
                for _, db in DICT_DBS:
                    results += _query_db(db, stem)
                if results:
                    break
    if compact:
        for r in results:
            senses = json.loads(r["senses"])
            r["senses"] = [s[:120] for s in senses[:4]]
    return results


# ---------- 术语表 ----------

_glossary_cache = None


def load_glossary():
    global _glossary_cache
    if _glossary_cache is None:
        raw = {}  # bo -> (zh, freq, human)
        if GLOSSARY.exists():
            for i, line in enumerate(GLOSSARY.open(encoding="utf-8")):
                if i == 0:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    bo, zh, freq = parts[0], parts[1], int(parts[2])
                    human = len(parts) >= 4 and "人工校正" in parts[3]
                    prev = raw.get(bo)
                    # 人工校正条目永远优先；同类内频次高者胜
                    if prev is None or (human and not prev[2]) \
                            or (human == prev[2] and freq > prev[1]):
                        raw[bo] = (zh, freq, human)
        _glossary_cache = {k: (v[0], v[1]) for k, v in raw.items()}
    return _glossary_cache


def scan_glossary(bo_text: str, max_len=8):
    """在一段藏文上最长匹配术语表，返回 [(藏文, 规范汉译, 频次)]。"""
    g = load_glossary()
    syls = syllables(bo_text)
    hits, i, n = [], 0, len(syls)
    while i < n:
        matched = None
        for l in range(min(max_len, n - i), 1, -1):
            cand = "་".join(syls[i:i + l])
            if cand in g:
                matched = cand
                break
        if matched:
            zh, freq = g[matched]
            hits.append((matched, zh, freq))
            i += len(matched.split("་"))
        else:
            i += 1
    # 去重保序
    seen, out = set(), []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            out.append(h)
    return out


# ---------- 翻译记忆 ----------

_tm_cache = None


def load_tm():
    global _tm_cache
    if _tm_cache is None:
        segs = []
        for p in TM_FILES:
            if p.exists():
                for line in p.open(encoding="utf-8"):
                    s = json.loads(line)
                    if s.get("bo") and s.get("zh"):
                        s["_syls"] = set(syllables(s["bo"]))
                        segs.append(s)
        _tm_cache = segs
    return _tm_cache


def search_tm(bo_text: str, k=3):
    """按音节 Jaccard 相似度检索最像的历史译例。数据量小，线性扫即可。"""
    q = set(syllables(bo_text))
    if not q:
        return []
    scored = []
    for s in load_tm():
        inter = len(q & s["_syls"])
        if inter < 2:
            continue
        score = inter / len(q | s["_syls"])
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [{"score": round(sc, 3), "bo": s["bo"][:200], "zh": s["zh"][:200],
             "source": s["source"]} for sc, s in scored[:k]]
