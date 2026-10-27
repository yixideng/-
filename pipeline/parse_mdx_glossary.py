"""解析 MDX 导出的「梵-中-藏」词汇表（如《宝性论大疏》词汇表）为可建库的 JSONL。

源格式（每条数据集中在以 <b> 起首的那一行）：
    abhedārtha
    <b>abhedārtha </b><br><br>【中文】无别义 <br><br>【梵文转写】abhedārtha <br><br>【藏文】དབྱེར་མེད་པའི་དོན།
    </>

本词汇表以**梵文**为词头，而本仓库查词以**藏文**为键，故按【藏文】反向建索引：
取【藏文】字段（可含多个藏文形，以空格分隔）逐一作 headword（经 lookup_key 归一：
NFC＋去两端 shad/tsek），释义＝【中文】；同一藏文形在多条中出现则合并其多个中文义、
梵文转写并记。输出 JSONL 交 build_index.py 压成 sqlite。

用法：
    python3 pipeline/parse_mdx_glossary.py \
        data/raw/dictionaries/ratnagotra_glossary_mdx.txt \
        --source 宝性论大疏词汇表 \
        --out data/processed/ratnagotra_glossary.jsonl
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import lookup_key, nfc  # noqa: E402

_NOTE = "（《宝性论释》梵本中所未出现的词汇）"
RE_CN = re.compile(r"【中文】\s*(.*?)\s*(?:<br|【|$)")
RE_SA = re.compile(r"【梵文转写】\s*(.*?)\s*(?:<br|【|$)")
RE_BO = re.compile(r"【藏文】\s*(.*?)\s*$")
RE_TAG = re.compile(r"<[^>]*>")


def _clean(s: str) -> str:
    s = RE_TAG.sub("", s).replace(_NOTE, "")
    return " ".join(s.split()).strip(" ，,")


def parse(path: Path, source: str):
    # headword(归一藏文形) -> {"raw": 原形, "cn": [中文…], "sa": [梵…]}
    acc = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("<b>"):
            continue
        mcn, mbo = RE_CN.search(line), RE_BO.search(line)
        if not mbo:
            continue
        cn = _clean(mcn.group(1)) if mcn else ""
        if not cn:
            continue
        msa = RE_SA.search(line)
        sa = _clean(msa.group(1)) if msa else ""
        bo_field = RE_TAG.sub("", mbo.group(1)).strip()
        for form in bo_field.split():          # 多个藏文形以空格分隔
            form = nfc(form).strip()
            if not form:
                continue
            key = lookup_key(form)
            if not key or not any(0x0F00 <= ord(c) <= 0x0FFF for c in key):
                continue
            rec = acc.setdefault(key, {"raw": form.rstrip("།").rstrip("་"),
                                       "cn": [], "sa": []})
            if cn not in rec["cn"]:
                rec["cn"].append(cn)
            for one in (x.strip() for x in sa.split(",")):
                if one and one not in rec["sa"]:
                    rec["sa"].append(one)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--source", required=True, help="词源名（入库 entries.source）")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    acc = parse(args.src, args.source)
    n = 0
    with args.out.open("w", encoding="utf-8") as f:
        for key, rec in sorted(acc.items()):
            sa = "；".join(rec["sa"])
            rec_out = {
                "headword": key,
                "headword_raw": rec["raw"],
                "source": args.source,
                "pos": sa,
                "senses": rec["cn"],
                "full_text": "；".join(rec["cn"]) + (f"｜梵：{sa}" if sa else ""),
            }
            f.write(json.dumps(rec_out, ensure_ascii=False) + "\n")
            n += 1
    print(f"解析 {n} 条藏文词头 -> {args.out}")


if __name__ == "__main__":
    main()
