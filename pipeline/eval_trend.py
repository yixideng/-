"""评测基线：机器稿 ↔ 用户校正版，按段量化「还要改多少」，生成趋势表（进 Git）。

对每个同时有「机器稿留存」(review/_机器直译稿留存/<项目>_<段>_机器直译稿.md) 与
「校正版平行文」的段落：按藏文骨架对齐句子，比较汉译（去标点后字符级相似度）。
另统计该段校正版上「强制术语」被用户采用的比例（用当前术语库回测）。

    python3 pipeline/eval_trend.py            # 重算全部，写 review/_评测/趋势.md
    python3 pipeline/eval_trend.py --show     # 只打印不写

注意：机器稿须是流水线原样输出（勿在会话中手改 译文.md 再留存），否则相似度偏高。
早期个别段（如 6.9）留存稿已含会话中修正，数值偏乐观，表中标「*」。
"""
import argparse
import datetime
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tmlib  # noqa: E402
from agent import tools  # noqa: E402

ROOT = tmlib.ROOT
STASH = ROOT / "review/_机器直译稿留存"
OUT = ROOT / "review/_评测/趋势.md"
CONTAMINATED = {"6.9"}          # 留存稿含会话中修正者
_PUNCT = re.compile(r"[〔〕（）()「」『』《》〈〉，。：；、！？,.:;!?\s]")


def _has_bo(s):  return any(0x0F00 <= ord(c) <= 0x0FFF for c in s)
def _has_han(s): return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)
def _bo_key(s):  return "".join(c for c in s if 0x0F40 <= ord(c) <= 0x0FBC)


def pairs(path: Path):
    """{藏文骨架前60: 汉译} ——取「纯藏文行」与其后首个汉译行。"""
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    out = {}
    for i, l in enumerate(lines):
        if l.startswith("#"):
            break                                   # 文末校勘节不计
        if _has_bo(l) and not _has_han(l):
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines) and _has_han(lines[j]):
                out[_bo_key(l)[:60]] = lines[j]
    return out


def term_adoption(par: Path):
    hit = n = 0
    for bo_line, zh in pairs_raw(par):
        for _bo, z, _f, multi in tools.scan_glossary(bo_line):
            if multi:
                continue
            n += 1
            core = tools._CORE_CUT.split(z, 1)[0]
            if any(a.strip() and a.strip() in zh for a in re.split(r"[／/、，,]", core)):
                hit += 1
    return hit, n


def pairs_raw(path: Path):
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    for i, l in enumerate(lines):
        if _has_bo(l) and not _has_han(l):
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines) and _has_han(lines[j]):
                yield l, lines[j]


def section_of(stash: Path, prefix: str):
    m = re.match(rf"{prefix}_(.+?)_机器", stash.name)
    return m.group(1) if m else None


def evaluate(project: str = "gzhanstong"):
    prefix = tmlib.PROJECTS[project]["prefix"]
    pars = {tmlib._parts(p, project)[0]: p for p in tmlib.parallels(project)}
    rows = []
    for st in STASH.glob(f"{prefix}_*_机器直译稿.md"):
        sec = section_of(st, prefix)
        par = pars.get(sec)
        if not par:
            continue
        M, P = pairs(st), pairs(par)
        common = [k for k in M if k in P]
        if len(common) < 2:
            continue
        sims = [difflib.SequenceMatcher(None, _PUNCT.sub("", M[k]), _PUNCT.sub("", P[k])).ratio()
                for k in common]
        hit, n = term_adoption(par)
        rows.append({"sec": sec, "n": len(common), "sim": sum(sims) / len(sims),
                     "term": (hit / n) if n else None, "flag": "*" if sec in CONTAMINATED else ""})
    key = lambda r: [int(x) if x.isdigit() else x for x in re.split(r"[.]", re.sub(r"[a-z]$", "", r["sec"]))]
    return sorted(rows, key=key)


def render(rows):
    today = datetime.date.today().isoformat()
    L = ["# 评测趋势：机器稿 ↔ 用户校正版", "",
         f"> 自动生成（`python3 pipeline/eval_trend.py`），最近更新 {today}。",
         "> **相似度**＝按句对齐后汉译（去标点）字符级相似度，越高＝用户改得越少；",
         "> **改动率**≈1−相似度；**术语采用**＝该段校正版上强制术语被用户采用之比（以当前术语库回测）。",
         "> 「*」＝留存机器稿含会话中修正，数值偏乐观。", "",
         "| 段 | 对齐句数 | 相似度 | 改动率 | 术语采用 | 趋势 |", "|---|---|---|---|---|---|"]
    for r in rows:
        term = f"{r['term']:.0%}" if r["term"] is not None else "—"
        L.append(f"| {r['sec']}{r['flag']} | {r['n']} | {r['sim']:.2f} | {1 - r['sim']:.0%} | {term} | "
                 f"{'█' * round(r['sim'] * 20)} |")
    clean = [r for r in rows if not r["flag"]]
    if clean:
        recent = clean[-3:]
        L += ["", f"**近 3 段平均相似度 {sum(r['sim'] for r in recent) / len(recent):.2f}**"
                  f"（全部 {len(clean)} 段平均 {sum(r['sim'] for r in clean) / len(clean):.2f}，不含*）"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="只打印不写文件")
    ap.add_argument("--project", default="gzhanstong")
    a = ap.parse_args()
    md = render(evaluate(a.project))
    if a.show:
        print(md)
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md, encoding="utf-8")
    print(md)
    print(f"已写入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
