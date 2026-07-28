"""藏译汉流水线主程序。

流程：输入藏文 → 分段 → 检索（术语表/词典/翻译记忆）→ 组装翻译资料包
     → 交给 Claude 翻译（或 --packet 只输出资料包）。

用法：
    # 只生成资料包（不调用模型，便于检查检索质量）
    python agent/translator.py --text "བྱང་ཆུབ་སེམས་..." --packet

    # 完整翻译（经 claude CLI 调用模型）
    python agent/translator.py --file input.txt
    python agent/translator.py --text "..." --out result.md
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
import tools  # noqa: E402

PROMPT_FILE = ROOT / "agent/prompts/translate.md"


def split_segments(text: str, max_shad=8):
    """按 shad 分句，再把若干句聚成段（偈颂四句约两 shad 一句）。"""
    # 按 shad 切句；双 shad「། །」会把后一个 shad 甩到下句开头，需剥掉
    parts = [p.strip().lstrip("།༎ ").strip()
             for p in re.split(r"(?<=[།༎])", text)]
    parts = [p for p in parts if p]
    segs, cur, cnt = [], [], 0
    for p in parts:
        cur.append(p)
        cnt += 1
        if cnt >= max_shad:
            segs.append(" ".join(cur))
            cur, cnt = [], 0
    if cur:
        segs.append(" ".join(cur))
    return segs


def build_packet(text: str) -> str:
    segs = split_segments(text)
    lines = []
    lines.append(PROMPT_FILE.read_text(encoding="utf-8"))
    lines.append("\n---\n## 待译原文（共 %d 段）\n" % len(segs))
    for i, s in enumerate(segs, 1):
        lines.append(f"[段{i}] {s}")

    # 术语约束（全篇扫描）
    glo = tools.scan_glossary(text)
    lines.append("\n## 术语约束（必须采用的译法）\n")
    if glo:
        for bo, zh, freq in glo:
            lines.append(f"- {bo} → **{zh}**（本传承译本中出现 {freq} 次）")
    else:
        lines.append("（本段未命中术语表）")

    # 词典释义：对术语表未覆盖的多音节词查词典
    covered = {g[0] for g in glo}
    dict_hits, seen = [], set()
    syls = tools.syllables(text)
    i = 0
    while i < len(syls):
        matched = None
        for l in range(min(8, len(syls) - i), 1, -1):
            cand = "་".join(syls[i:i + l])
            if cand in seen or cand in covered:
                continue
            res = tools.lookup_dict(cand)
            if res:
                matched = (cand, res)
                break
        if matched:
            seen.add(matched[0])
            dict_hits.append(matched)
            i += len(matched[0].split("་"))
        else:
            i += 1
    lines.append("\n## 词典释义（参考）\n")
    for word, entries in dict_hits[:25]:
        for e in entries[:2]:
            sense = "；".join(e["senses"])[:150]
            lines.append(f"- {word}〔{e['source']}〕{sense}")

    # 相似译例
    lines.append("\n## 参考译例（同一译者已定稿译本，模仿其文体）\n")
    for i, s in enumerate(segs, 1):
        for ex in tools.search_tm(s, k=2):
            if ex["score"] >= 0.15:
                lines.append(f"- 〔{ex['source']}｜相似度{ex['score']}〕")
                lines.append(f"  藏：{ex['bo']}")
                lines.append(f"  汉：{ex['zh']}")

    lines.append("\n---\n请按系统指令逐段翻译上方【待译原文】。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--file", type=Path)
    ap.add_argument("--packet", action="store_true", help="只输出资料包，不调用模型")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--model", default="")
    args = ap.parse_args()

    text = args.text or (args.file.read_text(encoding="utf-8") if args.file else None)
    if not text:
        ap.error("需要 --text 或 --file")

    packet = build_packet(text)
    if args.packet:
        print(packet)
        return

    cmd = ["claude", "-p"]
    if args.model:
        cmd += ["--model", args.model]
    r = subprocess.run(cmd, input=packet, capture_output=True, text=True, timeout=600)
    out = r.stdout.strip() or r.stderr.strip()
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
        print(f"译文已写入 {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
