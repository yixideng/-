"""校正版回流·机械部分一条命令完成（判断性的术语/法义/句法/校订本仍由人·AI 斟酌）。

    python3 pipeline/reflow.py review/gzhanstong_6.11_<题>_parallel.txt \
        --draft data/raw/source_texts/译文_品六_6.11_<题>.md

做四件事：
  1. 平行文 → 对齐为译例 data/processed/tm_<项目>_<段>.jsonl（tools.py 自动加载，无需登记）
  2. --draft 给出时：把**流水线原样输出**的机器稿留存到 review/_机器直译稿留存/（供评测与文风 diff）
  3. 重算评测趋势表 review/_评测/趋势.md，并报本段相似度
  4. 列出其余须人工判断的归档步骤（术语库／法义／句法·文风／校订本）
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmlib  # noqa: E402

ROOT = tmlib.ROOT
STASH = ROOT / "review/_机器直译稿留存"


def half_width_hits(par: Path):
    """校正版平行文汉译行里的半角 , ; : ! ? ( ) —— 返回 [(行号, 字符, 上下文)]。"""
    hits = []
    for i, l in enumerate(par.read_text(encoding="utf-8").splitlines(), 1):
        if any(0x0F00 <= ord(c) <= 0x0FFF for c in l[:3]) or not any(0x4E00 <= ord(c) <= 0x9FFF for c in l):
            continue
        for m in re.finditer(r"[,;:!?()]", l):
            hits.append((i, m.group(), l[max(0, m.start() - 8):m.start() + 6]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parallel", type=Path, help="校正版平行文（藏/汉 交替行）")
    ap.add_argument("--project", default="gzhanstong")
    ap.add_argument("--draft", type=Path, help="流水线原样输出的 译文.md（勿用手改过的）")
    a = ap.parse_args()

    par = a.parallel if a.parallel.is_absolute() else ROOT / a.parallel
    if not par.exists():
        sys.exit(f"找不到平行文 {par}")
    sec, _ = tmlib._parts(par, a.project)
    prefix = tmlib.PROJECTS[a.project]["prefix"]

    halfw = half_width_hits(par)
    if halfw:                                   # 校正版汉译行混入半角标点（全角铁律）→ 当场提示，不擅改
        print(f"⚠ 校正版汉译行有 {len(halfw)} 处半角标点（应全角）：")
        for ln, ch, ctx in halfw[:10]:
            print(f"   第{ln}行 「{ch}」 …{ctx}…")

    print("① 对齐入译例")
    out = tmlib.align_one(par, a.project)
    print(f"   → {out.relative_to(ROOT)}（自动加载，无需登记）")

    if a.draft:
        d = a.draft if a.draft.is_absolute() else ROOT / a.draft
        if not d.exists():
            sys.exit(f"找不到机器稿 {d}")
        STASH.mkdir(parents=True, exist_ok=True)
        dest = STASH / f"{prefix}_{sec}_机器直译稿.md"
        shutil.copyfile(d, dest)
        print(f"② 机器稿留存 → {dest.relative_to(ROOT)}")
    else:
        print("② 未给 --draft，跳过机器稿留存（本段将不进评测）")

    print("③ 评测")
    r = subprocess.run([sys.executable, str(ROOT / "pipeline/eval_trend.py"), "--project", a.project],
                       capture_output=True, text=True)
    row = [l for l in r.stdout.splitlines() if l.startswith(f"| {sec} ") or l.startswith(f"| {sec}*")]
    print("   " + (row[0] if row else "（本段无机器稿或对齐句不足，未计）"))
    avg = [l for l in r.stdout.splitlines() if l.startswith("**近 3 段")]
    if avg:
        print("   " + avg[0])

    print("④ 其余须斟酌归档（四类各归其家）：")
    print("   - 术语：校正版「」所标术语逐一核 glossary/glossary.tsv（无则收·有而不一则补词干/前缀形）")
    print("   - 法义：notes/法义.md 追加本段纪要（自动按需注入，不必顾虑篇幅）")
    print("   - 句法/文风：diff 机器稿↔校正版，可泛化之规律入 notes/句法.md / notes/文风.md")
    print("     · 新节默认＝通则（恒常注入）；只管特定词/结构的才在标题下加 <!-- 触发：A|B -->")
    print("     · 用户明确裁定者直接生效；仅由 diff 归纳、用户未表态者加 <!-- 状态：观察 -->")
    print("     · 新规取代旧节：旧节加 <!-- 状态：废止｜取代：§N -->（原文留档、不再注入）")
    print(f"   - 校订本：review/{prefix}_{sec}_…_校订本.md（根颂·汉传引文·前译↔校正差异）")
    print("   - 末了：python3 pipeline/audit_glossary.py 体检术语；python3 pipeline/audit_notes.py 体检笔记触发；"
          "git commit && git push")


if __name__ == "__main__":
    main()
