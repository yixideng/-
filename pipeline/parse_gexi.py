"""《格西曲扎藏文词典》解析器。

格式（比藏汉大辞典简单得多）：
    ཀ་ཀ་ཎི
    <b>།ཀ་ཀ་ཎི།</b><br><br>﹝梵﹞[藏文释义] 迦迦尼，金钱名… <b>@0001</b>\t
    </>

要点：
  - 记录以 </> 分隔；纯文本词头行在 <b> 之前
  - <b>།词头།</b> 为词头；<b>@NNNN</b> 为页码
  - 语种/来源标注在半角括号内：﹝梵﹞﹝达﹞﹝汉﹞﹝蒙﹞… 与【增】
  - 义项用罗马数字 Ⅰ.Ⅱ. 或阿拉伯 1.2.
  - 交叉参见：「即 XXX」「（同）XXX」

输出与 parse_dict.py 同一套 Entry schema，可直接交给 build_index.py。

用法：
    python pipeline/parse_gexi.py data/raw/dictionaries/gexi_full.txt \
        --out data/processed/gexi.jsonl --stats
"""
import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import nfc, lookup_key, clean_ws  # noqa: E402

SOURCE = "格西曲扎藏文词典"
RECORD_SEP = "</>"
TAG_RE = re.compile(r"<[^>]+>")
RE_PAGE = re.compile(r"@\s*(\d+)")
RE_BRACKET_TAG = re.compile(r"[﹝【]\s*([^﹞】]{1,6}?)\s*[﹞】]")
RE_ROMAN = re.compile(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.")
RE_ARABIC = re.compile(r"(?<![0-9])[1-9]\.")
# 交叉参见后紧跟的藏文串
RE_XREF = re.compile(r"(?:即|（同）|\(同\))\s*([ༀ-࿿][ༀ-࿿ ]*)")


@dataclass
class Entry:
    headword: str
    headword_raw: str
    alt_forms: list = field(default_factory=list)
    source: str = SOURCE
    page: str = ""
    pos: str = ""
    tags: list = field(default_factory=list)
    senses: list = field(default_factory=list)
    bo_examples: list = field(default_factory=list)
    full_text: str = ""


def _clean(fragment: str) -> str:
    txt = fragment.replace("<br>", " ").replace("<br/>", " ")
    txt = TAG_RE.sub("", txt)
    return html.unescape(txt)


def _split_senses(body: str):
    body = RE_PAGE.sub("", body)
    body = clean_ws(body)
    if not body:
        return []
    if RE_ROMAN.search(body):
        parts = RE_ROMAN.split(body)
    elif RE_ARABIC.search(body):
        parts = RE_ARABIC.split(body)
    else:
        parts = [body]
    return [clean_ws(p) for p in parts if clean_ws(p)]


def parse_record(chunk: str) -> Entry | None:
    if "<b>" not in chunk:
        return None
    # 词头行：首个 <b> 之前的纯文本；正文从首个 <b> 起算（排除词头行本身）
    m = re.search(r"<b>", chunk)
    head_line = clean_ws(TAG_RE.sub("", chunk[:m.start()]))

    body_full = nfc(clean_ws(_clean(chunk[m.start():])))
    if not body_full:
        return None

    # 词头：优先纯文本行，回退到正文首个 shad 词头
    raw_head = head_line
    if not raw_head:
        mh = re.match(r"\s*།?([ༀ-࿿ ]+?)།", body_full)
        raw_head = clean_ws(mh.group(1)) if mh else ""
    headword = lookup_key(raw_head)
    if not headword:
        return None

    # 页码
    mpage = RE_PAGE.search(body_full)
    page = mpage.group(1) if mpage else ""

    # 标签（语种/来源/增补）
    tags = []
    for t in RE_BRACKET_TAG.findall(body_full):
        t = clean_ws(t)
        if t and t not in tags:
            tags.append(t)

    # 交叉参见 -> 异体
    alt_forms = []
    for mx in RE_XREF.finditer(body_full):
        alt = lookup_key(mx.group(1))
        if alt and alt != headword and alt not in alt_forms:
            alt_forms.append(alt)

    # 正文：剥掉开头第一个 shad 包裹的词头段（།词头།），不依赖字符串精确匹配
    body = re.sub(r"^\s*།[^།]*།\s*", "", body_full, count=1)
    senses = _split_senses(body)

    return Entry(
        headword=headword, headword_raw=nfc(raw_head), alt_forms=alt_forms,
        page=page, tags=tags, senses=senses, full_text=body_full,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/processed/gexi.jsonl"))
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    text = args.input.read_text(encoding="utf-8", errors="replace")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    n, tagged, paged = 0, 0, 0
    with args.out.open("w", encoding="utf-8") as f:
        for chunk in text.split(RECORD_SEP):
            e = parse_record(chunk)
            if e is None:
                continue
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
            n += 1
            tagged += bool(e.tags)
            paged += bool(e.page)

    print(f"解析词条 {n} 条 -> {args.out}")
    if args.stats:
        print(f"  带标签: {tagged}  带页码: {paged}")


if __name__ == "__main__":
    main()
