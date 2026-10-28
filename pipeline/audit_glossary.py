"""术语库体检：用用户校正版平行文实测「强制术语」的命中率，低命中者降级为「参考」。

原理：对 review/ 下每份校正版平行文的每个藏文行，按流水线同样的方式
(tools.scan_glossary) 找出会被「强制」的术语；再看该句**用户定稿汉译**里是否
确实用了此译名（核心词任一异写出现即算命中）。命中率低＝该强制约束在真实语境里
常常是错的（如 ཡོད་པ→实有、གསལ་བ→显明），应改为「参考」不再强制。

只审非用户层条目（自动抽取/人工校正），**用户裁定/校订本条目永不降级**。
降级＝在其出处列追加「｜参考(校正命中a/n)」，不删除数据，可随时撤回。

用法：
    python3 pipeline/audit_glossary.py              # 只出报告
    python3 pipeline/audit_glossary.py --apply      # 按阈值落盘降级
    python3 pipeline/audit_glossary.py --min-n 5 --zero-n 3 --max-rate 0.34
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import tools  # noqa: E402

GLOSSARY = ROOT / "glossary/glossary.tsv"


def _has_bo(s):  return any(0x0F00 <= ord(c) <= 0x0FFF for c in s)
def _has_han(s): return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)


def parallel_pairs():
    """遍历 review/ 校正版平行文，产出 (藏文行, 汉译行)。"""
    for p in sorted((ROOT / "review").glob("gzhanstong_*.txt")):
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()]
        for i, l in enumerate(lines):
            if _has_bo(l) and not _has_han(l):
                j = i + 1
                while j < len(lines) and not lines[j]:
                    j += 1
                if j < len(lines) and _has_han(lines[j]) and not _has_bo(lines[j][:1]):
                    yield l, lines[j]


def core_alts(zh: str):
    core = tools._CORE_CUT.split(zh, 1)[0]
    alts = [a.strip(" 「」『』") for a in re.split(r"[／/、，,]", core)]
    return [a for a in alts if a]


def audit():
    g = tools.load_glossary()
    stat = defaultdict(lambda: [0, 0])          # bo -> [命中, 触发]
    for bo_line, zh_line in parallel_pairs():
        for bo, zh, _freq, multi in tools.scan_glossary(bo_line):
            if multi:
                continue
            stat[bo][1] += 1
            if any(a in zh_line for a in core_alts(zh)):
                stat[bo][0] += 1
    return g, stat


def user_tier_wins(bo):
    rows = [l.rstrip("\n").split("\t") for i, l in
            enumerate(GLOSSARY.open(encoding="utf-8")) if i > 0]
    return any(r[0] == bo and len(r) > 3 and ("用户" in r[3] or "校订本" in r[3]) for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落盘降级")
    ap.add_argument("--min-n", type=int, default=5, help="触发≥此次数才按命中率评")
    ap.add_argument("--zero-n", type=int, default=3, help="触发≥此次数且零命中亦降级")
    ap.add_argument("--max-rate", type=float, default=0.34, help="命中率低于此值降级为参考(不进资料包)")
    ap.add_argument("--soft-rate", type=float, default=0.60, help="命中率介于max~soft之间→改多义·非强制(仍提示)")
    args = ap.parse_args()

    g, stat = audit()
    rows = [l.split("\t") for l in GLOSSARY.read_text(encoding="utf-8").splitlines()]
    user_bo = {r[0] for r in rows[1:] if len(r) > 3 and ("用户" in r[3] or "校订本" in r[3])}
    demote = []
    for bo, (hit, n) in stat.items():
        low = (n >= args.min_n and hit / n < args.max_rate) or (n >= args.zero_n and hit == 0)
        if low and bo not in user_bo:
            demote.append((bo, hit, n, g[bo][0]))
    demote.sort(key=lambda x: (x[1] / x[2], -x[2]))
    dset_bo = {d[0] for d in demote}
    soften = sorted([(bo, h, n, g[bo][0]) for bo, (h, n) in stat.items()
                     if bo not in dset_bo and bo not in user_bo and n >= args.min_n
                     and args.max_rate <= h / n < args.soft_rate and not g[bo][2]],
                    key=lambda x: x[1] / x[2])

    total = sum(n for _, n in stat.values())
    hits = sum(h for h, _ in stat.values())
    print(f"强制术语触发 {total} 次，用户定稿采用 {hits} 次，总体命中率 {hits / max(total, 1):.0%}")
    print(f"拟降级为「参考」（触发≥{args.min_n}且命中率<{args.max_rate:.0%}，或触发≥{args.zero_n}且零命中·非用户条目）：{len(demote)} 个")
    for bo, hit, n, zh in demote:
        print(f"  {hit:>3}/{n:<3} {bo} → {zh[:40]}")

    print(f"拟改为「多义·非强制」（命中率 {args.max_rate:.0%}~{args.soft_rate:.0%}）：{len(soften)} 个")
    for bo, hit, n, zh in soften:
        print(f"  {hit:>3}/{n:<3} {bo} → {zh[:40]}")

    if args.apply and (demote or soften):
        dset = {d[0]: f"｜参考(校正命中{d[1]}/{d[2]})" for d in demote}
        dset.update({d[0]: f"｜多义·非强制(校正命中{d[1]}/{d[2]})" for d in soften})
        out = [rows[0]]
        for r in rows[1:]:
            src0 = r[3] if len(r) > 3 else ""
            if len(r) >= 3 and r[0] in dset and "参考" not in src0 and "非强制" not in src0 \
                    and "用户" not in src0 and "校订本" not in src0:
                while len(r) < 4:
                    r.append("")
                r[3] = r[3] + dset[r[0]]
            out.append(r)
        GLOSSARY.write_text("\n".join("\t".join(r) for r in out) + "\n", encoding="utf-8")
        print(f"已落盘：降级参考 {len(demote)} 个，改多义·非强制 {len(soften)} 个")


if __name__ == "__main__":
    main()
