"""平行译本对齐 + 分层清洗。

输入：藏文行 / 汉文行 交替的译本 txt。
输出：JSONL，每条一个对齐段：
    {
      bo:         清洗后的藏文（去叶码等）
      zh:         清洗后的汉译正文（剥离括号注）
      zh_raw:     汉译原文（保留括号注）
      annotations:[...]  从汉译中剥出的括号注（解释/宗派/梵文原词等）
      type:       body（正文）| heading（科判）| chapter（章品）| colophon（品末结语）
      folios:     [...]  该段藏文中出现的叶码，如 7b
      source:     书名
    }

对齐策略：文件是「连续藏文块 → 连续汉文块」交替出现，
按此把每个「藏文块+紧随的汉文块」配成一个段（段级对齐）。
韵文（每句藏/汉一行）自然成 1:1；注疏长段成段级对照，均可用于术语抽取与翻译记忆。

用法：
    python pipeline/align.py data/raw/parallel/sample2_zhongguan.txt \
        --source "极广胜乘中观决定" --out data/processed/tm_zhongguan.jsonl --stats
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import nfc, clean_ws  # noqa: E402

RE_FOLIO = re.compile(r"\(?\s*(\d+[ab])\s*\)")          # 叶码 (7b) / 7b
RE_PAREN = re.compile(r"[（(]([^（()）]*)[)）]")           # 括号注（含中英括号）
RE_CHAPTER_ZH = re.compile(r"^第[一二三四五六七八九十百]+品")
RE_CHAPTER_BO = re.compile(r"རབ་ཏུ་བྱེད་པ")
# 科判：汉文以（天干/地支[数字]）开头，如（戊二）（已一）（庚一）
RE_HEADING_ZH = re.compile(r"^\s*[（(][甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥]")
RE_COLOPHON_ZH = re.compile(r"所说为.*品|品[。.]?\s*$")

YIGO = "༄༅༆༇༈"  # 藏文起首装饰符


def has_bo(s):
    return any(0x0F00 <= ord(c) <= 0x0FFF for c in s)


def has_zh(s):
    return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)


def line_lang(s):
    b, z = has_bo(s), has_zh(s)
    if b and not z:
        return "bo"
    if z and not b:
        return "zh"
    if b and z:
        return "mix"
    return "other"


def clean_bo(s):
    folios = RE_FOLIO.findall(s)
    s = RE_FOLIO.sub("", s)
    s = s.lstrip(YIGO + "། ")          # 去起首装饰与 shad
    return clean_ws(nfc(s)), folios


def clean_zh(s):
    annos = [clean_ws(a) for a in RE_PAREN.findall(s) if clean_ws(a)]
    body = clean_ws(RE_PAREN.sub("", s))
    return body, annos


def classify(bo, zh):
    if RE_CHAPTER_ZH.search(zh) or RE_CHAPTER_BO.search(bo):
        return "chapter"
    if RE_HEADING_ZH.search(zh):
        return "heading"
    if RE_COLOPHON_ZH.search(zh) and len(zh) < 40:
        return "colophon"
    return "body"


def segments(lines):
    """把交替的藏/汉块配对：连续藏文块 + 紧随的连续汉文块 = 一段。"""
    cur_bo, cur_zh = [], []
    for l in lines:
        lang = line_lang(l)
        if lang == "bo":
            if cur_zh:                       # 上一段汉文结束，输出
                yield cur_bo, cur_zh
                cur_bo, cur_zh = [], []
            cur_bo.append(l)
        elif lang == "zh":
            cur_zh.append(l)
        elif lang == "mix":                  # 藏汉同行，两边都收
            if cur_zh:
                yield cur_bo, cur_zh
                cur_bo, cur_zh = [], []
            cur_bo.append(l)
            cur_zh.append(l)
    if cur_bo or cur_zh:
        yield cur_bo, cur_zh


def align(path: Path, source: str):
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").split("\n") if l.strip()]
    out = []
    for bo_lines, zh_lines in segments(lines):
        bo_raw = clean_ws(" ".join(bo_lines))
        zh_rawtext = clean_ws(" ".join(zh_lines))
        bo, folios = clean_bo(bo_raw)
        zh, annos = clean_zh(zh_rawtext)
        if not bo and not zh:
            continue
        out.append({
            "bo": bo,
            "zh": zh,
            "zh_raw": zh_rawtext,
            "annotations": annos,
            "type": classify(bo_raw, zh_rawtext),
            "folios": folios,
            "source": source,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    rows = align(args.input, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"对齐 {len(rows)} 段 -> {args.out}")
    if args.stats:
        from collections import Counter
        types = Counter(r["type"] for r in rows)
        anno = sum(len(r["annotations"]) for r in rows)
        both = sum(1 for r in rows if r["bo"] and r["zh"])
        print(f"  段类型: {dict(types)}")
        print(f"  藏汉双全的段: {both}  剥出括号注: {anno} 条")


if __name__ == "__main__":
    main()
