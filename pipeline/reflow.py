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
import tmlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import tools  # noqa: E402

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


def unadopted_terms(par: Path):
    """校正版里「强制术语未被采用」者：[(藏文, 强制译名, 用户句片段)]，同词只列首见。
    回流原只收「」所标术语，用户未加引号而一贯改掉的普通用字（6.17 前 འབྲེལ་བ 相属→关联 31 次）从未回流；
    逐段列出，令每次改字都可见。错配（子串误配）亦会列出，判断时一并排除。"""
    seen, out = set(), []
    lines = [l.strip() for l in par.read_text(encoding="utf-8").splitlines() if l.strip()]
    for bo, zh in zip(lines, lines[1:]):
        if not tools._has_bo(bo) or tools._has_han(bo) or not tools._has_han(zh):
            continue
        for t, z, _f, multi in tools.scan_glossary(bo):
            if multi or t in seen:
                continue
            alts = tools.term_alts(z)
            if alts and not any(a in zh for a in alts):
                seen.add(t)
                core = tools._CORE_CUT.split(z, 1)[0]
                out.append((t, core, zh[:40]))
    return out


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

    unadopted = unadopted_terms(par)
    if unadopted:                               # 用户未加「」、却一贯改掉的用字（如 འབྲེལ་བ 相属→关联），靠此显形
        print(f"⚠ 强制术语本段未被校正版采用 {len(unadopted)} 处（逐条判断：收新译名／改按语境／属错配）：")
        for bo, zh, ctx in unadopted[:30]:
            print(f"   {bo} →「{zh}」 ‖ 校正版：…{ctx}…")

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
    print(f"   - 新收术语必验：python3 pipeline/audit_glossary.py --check-src {sec}校正版"
          "（历史校正版采用率低＝本段语境译法被泛化成全书强制，改「按语境」多义）")
    print("   - 笔记以效果为主·去冗余（用户裁定·恒常）：新规能并入既有条目则并（语序→文风§0.3 子项）；"
          "同一规律散见多节者合并、被覆盖者删并；规则所管句型仍照错＝未生效，改放置或改脚本质检，不再加字；"
          "报告常驻字数变化（audit_notes 末行）")
    print("   - 末了：python3 pipeline/audit_glossary.py 体检术语；python3 pipeline/audit_notes.py 体检笔记触发；"
          "git commit && git push")


if __name__ == "__main__":
    main()
