"""解析 MDX 导出的「梵-中-藏」词汇表为可建库的 JSONL（兼容两种版式）。

本仓库查词以**藏文**为键，而这类词汇表以**梵文**为词头，故按【藏文】反向建索引：
取藏文字段逐一作 headword（经 lookup_key 归一：NFC＋去两端 shad/tsek），释义＝中文。
同一藏文形在多条中出现则合并其多个中文义、梵文转写。输出 JSONL 交 build_index.py。

兼容两种版式（逐行自动判别）：
  A. 带标签（宝性论大疏词汇表）：
     <b>abhedārtha </b><br><br>【中文】无别义 <br><br>【梵文转写】abhedārtha <br><br>【藏文】དབྱེར་མེད་པའི་དོན།
  B. 无标签·按位置（瑜伽师地论词汇表）：
     <b>a-bala</b><br><br> 无力<br><br> མི་ཆོག།<br><br> mi chog
     —— <b>…</b> 内为梵文词头；其后 <br><br> 分隔的字段中，含汉字者＝中文、含藏文字符者＝藏文，
        末段威利转写(拉丁)忽略。多个藏文形以 ; ； ༚ 或空白分隔。

用法：
    python3 pipeline/parse_mdx_glossary.py <src.txt> --source <词源名> --out <out.jsonl>
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import lookup_key, nfc  # noqa: E402

_NOTE = "（《宝性论释》梵本中所未出现的词汇）"
RE_TAG = re.compile(r"<[^>]*>")
RE_BR = re.compile(r"<br\s*/?>", re.I)
RE_LBL_CN = re.compile(r"【中文】\s*(.*?)\s*(?:<br|【|$)")
RE_LBL_BO = re.compile(r"【藏文】\s*(.*?)\s*$")
RE_BO_SPLIT = re.compile(r"[;；༚]+|\s{1,}")


def _has_bo(s):  return any(0x0F00 <= ord(c) <= 0x0FFF for c in s)
def _has_han(s): return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)


def _clean_cn(s: str) -> str:
    s = RE_TAG.sub("", s).replace(_NOTE, "")
    s = re.sub(r"【[^】]*】", "", s)          # 去 【中文】/【梵文转写】等标签
    return " ".join(s.split()).strip(" ，,")


def _parse_line(line: str):
    """返回 (中文, 藏文串)；无法解析返回 (None, None)。"""
    body = line.strip()
    if not body.startswith("<b>"):
        return None, None
    body = re.sub(r"^<b>.*?</b>", "", body, count=1)   # 去梵文词头块
    if "【中文】" in line or "【藏文】" in line:          # A. 带标签
        mcn, mbo = RE_LBL_CN.search(line), RE_LBL_BO.search(line)
        cn = _clean_cn(mcn.group(1)) if mcn else ""
        bo = RE_TAG.sub("", mbo.group(1)).strip() if mbo else ""
        return cn, bo
    # B. 无标签·按位置：<br><br> 分段，取含汉字段=中文、含藏文段=藏文
    parts = [p.strip() for p in RE_BR.split(body) if p.strip()]
    cn = next((_clean_cn(p) for p in parts if _has_han(p)), "")
    bo = next((RE_TAG.sub("", p).strip() for p in parts if _has_bo(p)), "")
    return cn, bo


def parse(path: Path):
    acc = {}      # 归一藏文形 -> {"raw":原形, "cn":[中文…]}
    for line in path.read_text(encoding="utf-8").splitlines():
        cn, bo = _parse_line(line)
        if not cn or not bo:
            continue
        for form in RE_BO_SPLIT.split(bo):
            form = nfc(form).strip()
            if not form or not _has_bo(form):
                continue
            key = lookup_key(form)
            if not key or not _has_bo(key):
                continue
            rec = acc.setdefault(key, {"raw": form.rstrip("།").rstrip("་"), "cn": []})
            if cn not in rec["cn"]:
                rec["cn"].append(cn)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--source", required=True, help="词源名（入库 entries.source）")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    acc = parse(args.src)
    n = 0
    with args.out.open("w", encoding="utf-8") as f:
        for key, rec in sorted(acc.items()):
            rec_out = {
                "headword": key,
                "headword_raw": rec["raw"],
                "source": args.source,
                "senses": rec["cn"],
                "full_text": "；".join(rec["cn"]),
            }
            f.write(json.dumps(rec_out, ensure_ascii=False) + "\n")
            n += 1
    print(f"解析 {n} 条藏文词头 -> {args.out}")


if __name__ == "__main__":
    main()
