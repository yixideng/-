"""藏汉大辞典（混编 Word-HTML 导出）解析器。

输入：形如 data/raw/dictionaries/*.html 的文件。
      记录以 `</>` 分隔；每条记录 = 可选的纯文本词头行 + 一个 Word 导出的 HTML 片段。
      同一词头可有多条，分别来自《藏汉大辞典》和甘肃版《藏汉词典》，需分开保留。

输出：JSONL，每行一个词条（一个来源一条），字段见 Entry。

用法：
    python pipeline/parse_dict.py data/raw/dictionaries/sample_zhdcd.html \
        --out data/processed/dict.jsonl [--stats]
"""
import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import nfc, lookup_key, clean_ws, has_tibetan  # noqa: E402

RECORD_SEP = "</>"
SENSE_MARKS = "❶❷❸❹❺❻❼❽❾❿"          # 圆圈数字义项标记
SPAN_RE = re.compile(r"<span\b([^>]*)>(.*?)</span>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)

# 来源识别
RE_ZHDCD_PAGE = re.compile(r"藏汉大辞典\s*p\.?\s*(\d+)")
RE_GANSU = re.compile(r"甘肃版《藏汉词典》|甘肃版")
# 词性 〔名〕〔动〕...
RE_POS = re.compile(r"〔([^〕]+)〕")
# 语义标签 【ལེགས】【ཡུལ】... —— 括号内是藏文
RE_TAG = re.compile(r"【\s*([^】]+?)\s*】")
# 异体：词头行里的「亦作 XXX」
RE_ALT = re.compile(r"亦作\s*([ༀ-࿿ ་]+)")


@dataclass
class Entry:
    headword: str          # 规范化查询键（NFC + 去 shad/tsheg）
    headword_raw: str      # 原始词头（保留 shad）
    alt_forms: list = field(default_factory=list)
    source: str = ""       # 藏汉大辞典 / 甘肃版藏汉词典
    page: str = ""         # 藏汉大辞典页码，如 0001
    pos: str = ""          # 词性，如 名
    tags: list = field(default_factory=list)   # 语义/领域标签（藏文）
    senses: list = field(default_factory=list) # 各义项文本
    bo_examples: list = field(default_factory=list)  # 释义中出现的藏文例词/短语
    full_text: str = ""    # 全条重构文本（供 FTS 与模型阅读）


def _span_lang(attrs: str) -> str:
    """判断一个 span 的语言：bo / en / zh。"""
    a = attrs.lower()
    if "lang=bo" in a or 'lang="bo"' in a or "microsoft himalaya" in a:
        return "bo"
    if "lang=en" in a or 'lang="en' in a:
        return "en"
    return "zh"  # 微软雅黑 等，默认按中文处理


def _tokens_from_html(fragment: str):
    """把一段 HTML 拆成带语言标记的 token 序列：[(lang, text), ...]。

    非 span 包裹的裸文本（少见）也保留，按中文处理。
    """
    tokens = []
    pos = 0
    for m in SPAN_RE.finditer(fragment):
        # span 之间的裸文本
        gap = fragment[pos:m.start()]
        gap_txt = html.unescape(TAG_RE.sub("", gap))
        if gap_txt.strip():
            tokens.append(("zh", gap_txt))
        lang = _span_lang(m.group(1))
        inner = html.unescape(TAG_RE.sub("", m.group(2)))
        if inner:
            tokens.append((lang, nfc(inner) if lang == "bo" else inner))
        pos = m.end()
    tail = html.unescape(TAG_RE.sub("", fragment[pos:]))
    if tail.strip():
        tokens.append(("zh", tail))
    return tokens


def _tokens_to_text(tokens) -> str:
    return clean_ws("".join(t for _, t in tokens))


def parse_record(headword_line: str, html_block: str) -> Entry | None:
    if "<p" not in html_block:
        return None

    paras = P_RE.findall(html_block)
    if not paras:
        return None

    # 每个 <p> 转成 token 序列与纯文本
    para_tokens = [_tokens_from_html(p) for p in paras]
    para_texts = [_tokens_to_text(tk) for tk in para_tokens]
    full_text = clean_ws(" ".join(t for t in para_texts if t))

    # --- 词头 ---
    # 优先用记录前的纯文本词头行；缺失时回退到首个加粗 <p> 的 shad 词头
    raw_head = clean_ws(headword_line)
    if not raw_head:
        # 首段里的藏文即词头（形如 །ཀ་ཀ།）
        bo_first = "".join(t for lang, t in para_tokens[0] if lang == "bo")
        raw_head = clean_ws(bo_first)
    headword = lookup_key(raw_head)

    # --- 异体 ---
    alt_forms = []
    for m in RE_ALT.finditer(para_texts[0]):
        alt = lookup_key(m.group(1))
        if alt and alt != headword:
            alt_forms.append(alt)

    # --- 来源与页码 ---
    source, page = "", ""
    mpage = RE_ZHDCD_PAGE.search(full_text)
    if mpage:
        source, page = "藏汉大辞典", mpage.group(1)
    elif RE_GANSU.search(full_text):
        source = "甘肃版藏汉词典"

    # --- 词性 ---
    mpos = RE_POS.search(full_text)
    pos = mpos.group(1) if mpos else ""

    # --- 语义标签（藏文，需含藏文字符才算） ---
    tags = []
    for m in RE_TAG.finditer(full_text):
        tag = clean_ws(m.group(1))
        if has_tibetan(tag) and tag not in tags:
            tags.append(tag)

    # --- 义项切分（传入词头以剔除词头段） ---
    senses = _split_senses(para_texts, headword)

    # --- 藏文例词：释义正文里的藏文 token（排除词头本身与标签词） ---
    bo_examples = []
    for tk in para_tokens[1:]:  # 跳过词头段
        for lang, t in tk:
            if lang == "bo":
                for piece in re.split(r"[།༎]", t):
                    piece = lookup_key(piece)
                    if piece and piece != headword and piece not in tags \
                            and piece not in bo_examples:
                        bo_examples.append(piece)

    return Entry(
        headword=headword, headword_raw=raw_head, alt_forms=alt_forms,
        source=source, page=page, pos=pos, tags=tags,
        senses=senses, bo_examples=bo_examples, full_text=full_text,
    )


def _split_senses(para_texts, headword=""):
    """按 ❶❷❸ 或 (1)(2)(3) 切义项，去掉词头/词性/来源等噪声段。"""
    body = []
    for t in para_texts:
        if not t:
            continue
        if RE_POS.fullmatch(t.strip()):        # 纯 〔名〕 段
            continue
        # 纯词头段（形如 །ཀ་ཀ། 或含「亦作」的词头段）
        if headword and lookup_key(re.sub(r"亦作.*", "", t)) == headword:
            continue
        body.append(t)
    joined = " ".join(body)
    # 去掉末尾来源标注
    joined = re.sub(r"[（(]\s*(藏汉大辞典\s*p\.?\s*\d+|甘肃版《藏汉词典》)\s*[)）]?", "", joined)
    joined = clean_ws(joined)
    if not joined:
        return []

    # 优先 ❶❷❸
    if any(m in joined for m in SENSE_MARKS):
        parts = re.split(f"[{SENSE_MARKS}]", joined)
        return [clean_ws(p) for p in parts if clean_ws(p)]
    # 其次 (1)(2)(3)
    if re.search(r"\(\s*\d+\s*\)", joined):
        parts = re.split(r"\(\s*\d+\s*\)", joined)
        return [clean_ws(p) for p in parts if clean_ws(p)]
    return [joined]


def iter_records(text: str):
    """按 </> 切记录，产出 (headword_line, html_block)。

    纯文本词头行位于分隔符之后、下一个 <style> 之前。
    """
    chunks = text.split(RECORD_SEP)
    for chunk in chunks:
        if "<p" not in chunk:
            continue
        # <style> 或首个 <p 之前的内容视为词头行
        m = re.search(r"<style|<p\b", chunk, re.IGNORECASE)
        head = chunk[:m.start()] if m else ""
        # 去掉 <style>...</style>
        block = re.sub(r"<style\b.*?</style>", "", chunk, flags=re.DOTALL | re.IGNORECASE)
        # 词头行里可能残留藏文；仅取藏文/汉字文本行
        head = TAG_RE.sub("", head)
        yield head, block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/processed/dict.jsonl"))
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    text = args.input.read_text(encoding="utf-8", errors="replace")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    n, by_source = 0, {}
    with args.out.open("w", encoding="utf-8") as f:
        for head, block in iter_records(text):
            entry = parse_record(head, block)
            if entry is None or not entry.headword:
                continue
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
            n += 1
            by_source[entry.source or "?"] = by_source.get(entry.source or "?", 0) + 1

    print(f"解析词条 {n} 条 -> {args.out}")
    if args.stats:
        for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {s or '(未知来源)'}: {c}")


if __name__ == "__main__":
    main()
