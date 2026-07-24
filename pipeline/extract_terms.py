"""从对齐译例中抽取术语表：藏文术语 ↔ 译者实际采用的规范汉译。

方法（词典引导的共现统计）：
  1. 从两本词典取词头 -> 候选汉译集合（从义项文本切出短汉语词）
  2. 对每个对齐段：在藏文里做词典词头最长匹配，找出出现的术语；
     若该词头的某个候选汉译出现在同段汉译里，计一次共现
  3. 共现次数达阈值的 (藏文, 汉译) 对进入术语表，按频次排序
     —— 频次即「译者用此译法的次数」，天然反映本传承的规范译法

输出 glossary.tsv：藏文｜汉译｜频次｜例句出处。此文件人工可直接编辑增删。

用法：
    python pipeline/extract_terms.py \
        --tm data/processed/tm_zhongguan.jsonl data/processed/tm_baoxinglun.jsonl \
        --dicts data/processed/dict.jsonl data/processed/gexi.jsonl \
        --out data/processed/glossary.tsv --min-freq 2
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# 从义项文本切汉语候选译词：按标点/藏文断开，留 1~8 字纯汉串
RE_ZH_CHUNK = re.compile(r"[一-鿿]{1,8}")
STOP_GLOSS = {"名词", "动词", "形容词", "的", "之", "一种", "即", "同", "参看",
              "亦作", "等", "如", "与", "和", "或", "指", "为", "是", "有"}


def load_dict_glosses(paths, min_syl=2, max_syl=8):
    """词头 -> 候选汉译集合。只留 >=min_syl 音节的词头，避免单音节噪声。"""
    glosses = defaultdict(set)
    for p in paths:
        for line in Path(p).open(encoding="utf-8"):
            e = json.loads(line)
            hw = e["headword"]
            syls = [s for s in hw.split("་") if s]
            if not (min_syl <= len(syls) <= max_syl):
                continue
            for sense in e.get("senses", []):
                for zh in RE_ZH_CHUNK.findall(sense):
                    if 2 <= len(zh) <= 8 and zh not in STOP_GLOSS:
                        glosses[hw].add(zh)
    return glosses


def syllables(bo: str):
    return [s for s in re.split(r"[་།༎\s]+", bo) if s]


def maximal_match(syls, headwords, max_len=8):
    """在音节序列上做词典词头最长匹配，返回命中的词头列表。"""
    hits, i, n = [], 0, len(syls)
    while i < n:
        matched = None
        for l in range(min(max_len, n - i), 1, -1):   # 只匹配 >=2 音节
            cand = "་".join(syls[i:i + l])
            if cand in headwords:
                matched = cand
                break
        if matched:
            hits.append(matched)
            i += len(matched.split("་"))
        else:
            i += 1
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm", nargs="+", required=True)
    ap.add_argument("--dicts", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-freq", type=int, default=2)
    args = ap.parse_args()

    glosses = load_dict_glosses(args.dicts)
    headwords = set(glosses)
    print(f"词典桥梁：{len(headwords)} 个多音节词头")

    pair_freq = Counter()
    pair_src = defaultdict(set)
    seg_count = 0
    for tmp in args.tm:
        for line in Path(tmp).open(encoding="utf-8"):
            seg = json.loads(line)
            bo, zh = seg.get("bo", ""), seg.get("zh", "")
            if not bo or not zh:
                continue
            seg_count += 1
            for hw in set(maximal_match(syllables(bo), headwords)):
                # 取该词头在本段中命中的最长汉译（更具体者优先）
                found = [g for g in glosses[hw] if g in zh]
                if found:
                    best = max(found, key=len)
                    pair_freq[(hw, best)] += 1
                    pair_src[(hw, best)].add(seg["source"])

    rows = [(bo, zh, f, "、".join(sorted(pair_src[(bo, zh)])))
            for (bo, zh), f in pair_freq.items() if f >= args.min_freq]
    rows.sort(key=lambda r: -r[2])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        f.write("藏文\t汉译\t频次\t出处\n")
        for bo, zh, freq, src in rows:
            f.write(f"{bo}\t{zh}\t{freq}\t{src}\n")

    print(f"扫描 {seg_count} 段，抽出术语对 {len(rows)} 条（频次>={args.min_freq}） -> {args.out}")
    print("Top 20：")
    for bo, zh, freq, src in rows[:20]:
        print(f"  {freq:4d}  {bo}  ->  {zh}")


if __name__ == "__main__":
    main()
