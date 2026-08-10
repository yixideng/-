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
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
import tools  # noqa: E402

PROMPT_FILE = ROOT / "agent/prompts/translate.md"
# 笔记层（恒常注入）：法义纲要在前（先立框架），句法通则次之，文风通则在后
NOTES_FILES = [ROOT / "notes/法义.md", ROOT / "notes/句法.md", ROOT / "notes/文风.md"]
POLISH_FILE = ROOT / "agent/prompts/polish.md"


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
    # 笔记层：法义纲要 + 句法通则（恒常注入，先于原文，供全篇遵循）
    for nf in NOTES_FILES:
        if nf.exists():
            lines.append("\n---\n" + nf.read_text(encoding="utf-8"))
    lines.append("\n---\n## 待译原文（共 %d 段）\n" % len(segs))
    for i, s in enumerate(segs, 1):
        lines.append(f"[段{i}] {s}")

    # 术语约束（全篇扫描）
    glo = tools.scan_glossary(text)
    fixed = [g for g in glo if not g[3]]
    multi = [g for g in glo if g[3]]
    lines.append("\n## 术语约束（必须采用的译法）\n")
    if fixed:
        for bo, zh, freq, _ in fixed:
            lines.append(f"- {bo} → **{zh}**（本传承译本中出现 {freq} 次）")
    else:
        lines.append("（本段未命中术语表）")

    if multi:
        lines.append("\n## 多义词（依语境择一，非强制；判别线索见括号）\n")
        for bo, zh, _, _ in multi:
            lines.append(f"- {bo} → {zh}")

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


# 内层 claude 只做「纯文本任务」：prompt 已自带全部资料。关键防护：①在中性目录运行，避免加载
# 本仓库 CLAUDE.md（其"必须走流水线"会让内层误去递归跑 pipeline、卡在权限询问而非干活）；
# ②append-system-prompt 明确其唯一任务、禁用工具与反问。
def _run_claude(prompt: str, model: str, guard: str) -> str:
    cmd = ["claude", "-p", "--append-system-prompt", guard]
    if model:
        cmd += ["--model", model]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=3000, cwd=tempfile.gettempdir())
    return r.stdout.strip() or r.stderr.strip()


def _bo_line_count(text: str) -> int:
    """统计含藏文的行数（藏汉对照的『藏文行』数），用于润色前后段数比对。"""
    n = 0
    for ln in (text or "").splitlines():
        if any(0x0F00 <= ord(c) <= 0x0FFF for c in ln):
            n += 1
    return n


def build_polish_packet(draft: str, src_text: str) -> str:
    """第二遍润色资料包：润色规范 + 文风笔记 + 术语约束（守住不改）+ 直译稿。"""
    lines = [POLISH_FILE.read_text(encoding="utf-8")]
    wind = ROOT / "notes/文风.md"
    if wind.exists():
        lines.append("\n---\n" + wind.read_text(encoding="utf-8"))
    # 术语约束：让润色明确哪些译名必须保持不动
    glo = tools.scan_glossary(src_text)
    fixed = [g for g in glo if not g[3]]
    if fixed:
        lines.append("\n## 术语约束（润色时一律保持不动）\n")
        for bo, zh, _, _ in fixed:
            lines.append(f"- {bo} → **{zh}**")
    lines.append("\n---\n## 待润色·直译稿（藏文行照抄不动，仅重写汉译行）\n")
    lines.append(draft)
    lines.append("\n---\n请按【译文润色规范】只改行文、不动义理，输出润色后的藏汉逐段对照全文。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--file", type=Path)
    ap.add_argument("--packet", action="store_true", help="只输出资料包，不调用模型")
    ap.add_argument("--polish", action=argparse.BooleanOptionalAction, default=True,
                    help="翻译后再跑一遍『文风润色』（默认开；--no-polish 关）。两阶段：准确直译→定稿体润色")
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

    guard1 = ("你是藏译汉『译经引擎』。下方用户消息已含全部所需资料"
              "（系统指令·法义/句法/文风笔记·术语约束·词典释义·参考译例·待译原文）。"
              "唯一任务：按系统指令逐段输出藏汉逐段对照译文。"
              "严禁调用任何工具、运行脚本或本仓库流水线，严禁询问权限或反问，直接输出译文。")
    draft = _run_claude(packet, args.model, guard1)   # 第一遍：准确直译
    out = draft

    if args.polish:
        guard2 = ("你是藏译汉定稿润色师。下方已含直译稿·文风笔记·术语约束。"
                  "唯一任务：只改汉译行文、不动义理/术语/格式（藏文行照抄），输出润色后的对照全文。"
                  "严禁调用任何工具或反问，直接输出。")
        polished = _run_claude(build_polish_packet(draft, text), args.model, guard2)
        # 段数校验兜底：润色遍若擅自合并/拆分段落（藏文行数变化），弃用润色、保留直译，避免对照错位。
        n_draft, n_pol = _bo_line_count(draft), _bo_line_count(polished)
        if not polished:
            print("（润色遍无输出，保留直译稿）", file=sys.stderr)
        elif n_pol != n_draft:
            print(f"（润色遍段数漂移：直译 {n_draft} 段→润色 {n_pol} 段，已弃用润色、保留直译稿）",
                  file=sys.stderr)
        else:
            out = polished

    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
        print(f"译文已写入 {args.out}")
        # 润色时把纯直译稿一并另存，供日后「机器直译↔用户校正版」diff 提炼文风规律。
        if args.polish and out is not draft:
            draft_path = args.out.with_name(args.out.stem + "_直译" + args.out.suffix)
            draft_path.write_text(draft + "\n", encoding="utf-8")
            print(f"（纯直译稿另存 {draft_path}）")
    else:
        print(out)


if __name__ == "__main__":
    main()
