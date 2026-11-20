#!/usr/bin/env python3
"""整本翻译（不回流）：把一部藏文论著切块→逐块走 agent/translator.py→合并成全书译文。

    python3 pipeline/translate_book.py --book projects/jonang/待译/<书名>.txt --name <书名>
        [--project jonang] [--model claude-opus-5-5] [--chunk-chars 5000] [--limit N] [--dry-run]

- 切块：按空行分自然段累积到约 --chunk-chars 个藏文字符；单段过长则在句末（终结词＋shad）处断开，
  不腰斩句子、不切引语。块原文存 chunks/NNN_原文.txt。
- 逐块翻译：每块即一次 translator.py（默认两遍：直译→润色），产出 chunks/NNN_译文.md(+_直译/_质检)。
  **可断点续跑**：已有 NNN_译文.md 的块跳过；失败块记录后继续下一块，重跑即补。
- 合并：<书名>_全译.md（藏汉对照·各块校勘汇入文末附录）、<书名>_汉文.md（只汉文）、
  <书名>_质检汇总.md（各块质检＋失败块＋累计费用）。
- 产出目录 projects/<project>/books/<书名>/（进 Git，容器重置不丢）。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import translator as tr  # noqa: E402

_BO = re.compile(r"[ༀ-࿿]")


def _bo_len(s: str) -> int:
    return len(_BO.findall(s))


def _split_long(par: str, limit: int):
    """超长自然段在整句末断开（复用 translator 的句末/引语判定）。"""
    clauses = tr._shad_clauses(par)
    out, cur = [], []
    for i, c in enumerate(clauses):
        cur.append(c)
        nxt = clauses[i + 1] if i + 1 < len(clauses) else ""
        end = tr._sentence_end(c) and not tr._QUOTE_HEAD.match(nxt)
        if end and _bo_len(" ".join(cur)) >= limit:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def chunk_text(text: str, limit: int = 5000):
    """按空行分段累积成块（每块约 limit 个藏文字符）；超长段（>1.5·limit）句末断开。"""
    pars = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces = []
    for p in pars:
        pieces.extend(_split_long(p, limit) if _bo_len(p) > limit * 1.5 else [p])
    chunks, cur, n = [], [], 0
    for p in pieces:
        k = _bo_len(p)
        if cur and n + k > limit:
            chunks.append("\n\n".join(cur)); cur, n = [], 0
        cur.append(p); n += k
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def _cost(log: str) -> float:
    m = re.search(r"本次合计：.*?\$([0-9.]+)", log)
    return float(m.group(1)) if m else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=Path, required=True, help="整本藏文原文（UTF-8 txt；自然段以空行分隔为佳）")
    ap.add_argument("--name", required=True, help="书名（作产出目录名与文件名）")
    ap.add_argument("--project", default="jonang")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--chunk-chars", type=int, default=5000)
    ap.add_argument("--limit", type=int, default=0, help="本次最多翻几块（0=全部；试跑用）")
    ap.add_argument("--dry-run", action="store_true", help="只切块、报块数与预估费用，不调模型")
    a = ap.parse_args()

    out_dir = ROOT / "projects" / a.project / "books" / a.name
    cdir = out_dir / "chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    chunks = chunk_text(a.book.read_text(encoding="utf-8"), a.chunk_chars)
    total = sum(_bo_len(c) for c in chunks)
    print(f"《{a.name}》：藏文 {total:,} 字符 → {len(chunks)} 块（每块约 {a.chunk_chars}）；"
          f"预估费用约 ${total / 1000 * 0.2:.0f}（按 7.1 实测约 $0.2/千藏文字符）")
    for i, c in enumerate(chunks, 1):
        (cdir / f"{i:03d}_原文.txt").write_text(c + "\n", encoding="utf-8")
    if a.dry_run:
        return

    done = 0
    for i in range(1, len(chunks) + 1):
        src, dst = cdir / f"{i:03d}_原文.txt", cdir / f"{i:03d}_译文.md"
        if dst.exists():
            continue
        if a.limit and done >= a.limit:
            break
        print(f"[{i}/{len(chunks)}] 翻译中…", flush=True)
        cmd = [sys.executable, str(ROOT / "agent/translator.py"), "--project", a.project,
               "--file", str(src), "--out", str(dst), "--model", a.model]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        (cdir / f"{i:03d}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0 or not dst.exists():
            print(f"  ✗ 第 {i} 块失败（见 {i:03d}.log），继续下一块；重跑本命令即补", flush=True)
        else:
            print(f"  ✓ ${_cost(r.stderr):.2f}", flush=True)
        done += 1

    # 合并
    body, tails, zh, qa, fails, usd = [], [], [], [], [], 0.0
    for i in range(1, len(chunks) + 1):
        dst = cdir / f"{i:03d}_译文.md"
        log = cdir / f"{i:03d}.log"
        usd += _cost(log.read_text(encoding="utf-8")) if log.exists() else 0.0
        if not dst.exists():
            fails.append(i); body.append(f"〔第 {i} 块未译，见 chunks/{i:03d}_原文.txt〕"); continue
        b, t = tr._split_tail(dst.read_text(encoding="utf-8"))
        body.append(b)
        if t:
            tails.append(f"### 第 {i} 块\n\n{t}")
        zh.extend(ln for ln in b.splitlines() if ln.strip() and not _BO.search(ln))
        q = dst.with_name(dst.stem + "_质检" + dst.suffix)
        if q.exists():
            items = [ln for ln in q.read_text(encoding="utf-8").split("\n## ")[0].splitlines()
                     if ln.startswith("- ")]
            if items:
                qa.append(f"### 第 {i} 块\n" + "\n".join(items))
    full = f"# {a.name}（藏汉对照·机器译稿）\n\n" + "\n\n".join(body)
    if tails:
        full += "\n\n## 校勘附录（各块）\n\n" + "\n\n".join(tails)
    (out_dir / f"{a.name}_全译.md").write_text(full + "\n", encoding="utf-8")
    (out_dir / f"{a.name}_汉文.md").write_text(f"# {a.name}（汉译）\n\n" + "\n\n".join(zh) + "\n",
                                               encoding="utf-8")
    rep = [f"# 《{a.name}》质检汇总", "",
           f"- 块数 {len(chunks)}；已译 {len(chunks) - len(fails)}；未译 {len(fails)}"
           + (f"（第 {', '.join(map(str, fails))} 块）" if fails else ""),
           f"- 累计模型费用约 ${usd:.2f}", ""] + qa
    (out_dir / f"{a.name}_质检汇总.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"合并完成 → {out_dir}（未译 {len(fails)} 块·累计 ${usd:.2f}）")


if __name__ == "__main__":
    main()
