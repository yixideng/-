"""笔记层体检：专项规则的触发词是否靠得住、废止条目是否写明取代者、哪些节可能重复或冲突。

笔记（notes/句法.md 等）的节分两类（见 agent/translator.py `gate_sections`）：
无标注＝通则，恒常注入；`<!-- 触发：A|B -->`＝专项，待译含触发串才注入。
触发词写错，规则就静默不注入——本脚本以全部校正版平行文为语料实测，把这类风险报出来：

  ① 漏触发（最要紧）：节标题注明据某段立（如「品五 5.14」「据 6.12 diff」），
     却在该段原文上不触发；或本节自己举的藏文例句不触发本节——触发词没覆盖到它要管的文字。
  ② 死触发：在全部语料上一次都不触发（多半是触发串拼错/用了异写）。
  ③ 近乎常驻：在 ≥90% 的段触发，标成专项没意义，宜去掉标注改为通则。
  ④ 状态：废止节须写「取代：§N」且 §N 存在。
  ⑤ 疑重复/冲突（供人工看）：同一藏文结构式（反引号内、≥3 音节）在两节以上出现。

用法：
    python3 pipeline/audit_notes.py            # 报告；有①②④问题时退出码 1
    python3 pipeline/audit_notes.py --verbose  # 另列每个专项节在各段的触发情况
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import translator as T  # noqa: E402
from agent import tools  # noqa: E402


def corpus():
    """{段号: 该段全部藏文}——取自 review/ 校正版平行文（gzhanstong_<段号>_…_parallel.txt）
    与 data/raw/source_texts/待译_品X_<段号>….txt（尚未回流的段也算，如刚据其 diff 立的新规则）。"""
    out = defaultdict(list)
    srcs = [(p.name.split("_")[1], p) for p in sorted((ROOT / "review").glob("gzhanstong_*_parallel.txt"))]
    for p in sorted((ROOT / "data/raw/source_texts").glob("待译_品*.txt")):
        m = re.match(r"待译_品.+?_(\d+\.\d+[ab]?)", p.name)
        if m:
            srcs.append((m.group(1), p))
    for sid, p in srcs:
        out[sid] += [l for l in p.read_text(encoding="utf-8").splitlines()
                     if any(0x0F00 <= ord(c) <= 0x0FFF for c in l)]
    return {k: "\n".join(v) for k, v in out.items()}


def cited_sections(head: str, ids):
    """标题里注明的来源段号（5.14 / 5.13a / 5.16–5.17 / 5.21-22 / 6.5）→ 语料中存在者。"""
    found = set()
    for a, b in re.findall(r"(\d+\.\d+[ab]?)(?:\s*[–\-/／]\s*(\d+(?:\.\d+)?[ab]?))?", head):
        found.add(a)
        if b:
            found.add(b if "." in b else a.split(".")[0] + "." + b)
    return sorted(i for i in found if i in ids or any(k.startswith(i) for k in ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    cor = corpus()
    ids = list(cor)
    bad = 0
    always_chars = trig_chars = 0
    for nf in tools.project_notes():
        if not nf.exists():
            continue
        body = nf.read_text(encoding="utf-8")
        secs = [s for s in re.split(r"(?m)^(?=## )", body) if s.startswith("## ")]
        labels = {T._sec_label(s) for s in secs}
        print(f"\n## {nf.name}（{len(secs)} 节）")
        n_trig = 0
        for s in secs:
            meta = T._sec_meta(s)
            lab, head = T._sec_label(s), s.splitlines()[0]
            st = meta.get("状态", "")
            if st.startswith("废止"):
                m = re.search(r"取代[：:]\s*(§?\d+)", st)
                tgt = m and ("§" + m.group(1).lstrip("§"))
                if not tgt or tgt not in labels:
                    print(f"  ✗ {lab} 已废止但未写明有效取代者（取代：§N）")
                    bad += 1
                continue
            if "触发" not in meta:
                always_chars += len(s)
                continue
            n_trig += 1
            trig_chars += len(s)
            fired = [i for i in ids if T.trigger_hit(s, cor[i])]
            rate = len(fired) / max(len(ids), 1)
            src = [i for i in ids for c in cited_sections(head, ids) if i == c or i.startswith(c)]
            miss = [i for i in src if i not in fired]
            if miss:
                print(f"  ✗ {lab} 漏触发：据 {'/'.join(miss)} 立，却在该段原文上不触发——补触发词")
                bad += 1
            # 自例：本节自己举的藏文例句（≥5 音节·无省略号）须能触发本节，否则触发词没覆盖到规则本身
            own = [e for e in re.findall(r"`([^`]+)`", s)
                   if T._norm_tsheg(e).count("་") >= 4 and not re.search(r"[A-Za-z…<>↔/／]|\.\.\.", e)]
            own_miss = [e for e in own if not T.trigger_hit(s, e)]
            if own_miss:
                print(f"  ✗ {lab} 漏触发（自例）：本节例句不触发本节——{'、'.join(own_miss[:3])}")
                bad += 1
            if not fired:
                print(f"  ✗ {lab} 死触发：全部 {len(ids)} 段语料一次未触发——查触发串拼写/异写")
                bad += 1
            elif rate >= 0.9:
                print(f"  △ {lab} 近乎常驻：{len(fired)}/{len(ids)} 段触发——宜去掉触发标注改为通则")
            if args.verbose:
                print(f"    {lab} 触发 {len(fired)}/{len(ids)} 段" + (f"·来源段 {'/'.join(src)} ✓" if src and not miss else ""))
        print(f"  专项 {n_trig} 节·通则 {len(secs) - n_trig} 节")

    # ⑤ 疑重复/冲突：同一藏文结构式见于多节（跨文件）
    where = defaultdict(set)
    for nf in tools.project_notes():
        if not nf.exists():
            continue
        for s in re.split(r"(?m)^(?=## )", nf.read_text(encoding="utf-8")):
            if not s.startswith("## "):
                continue
            for pat in set(re.findall(r"`([^`]+)`", s)):
                p = T._norm_tsheg(pat).strip("་ ")
                if p.count("་") >= 2 and not re.search(r"[A-Za-z…]", p):
                    where[p].add(f"{nf.stem}{T._sec_label(s)}")
    dup = sorted(((p, w) for p, w in where.items() if len(w) >= 2), key=lambda x: -len(x[1]))
    print(f"\n## 疑重复/冲突（同一藏文结构式见于多节，供人工核对是否前后一致）：{len(dup)} 处")
    for p, w in dup[:30]:
        print(f"  {p}  ← {' ｜ '.join(sorted(w))}")
    if len(dup) > 30:
        print(f"  …另 {len(dup) - 30} 处")

    tot = always_chars + trig_chars
    print(f"\n笔记体量：通则 {always_chars:,} 字恒常注入·专项 {trig_chars:,} 字按触发注入"
          f"（专项占 {trig_chars / max(tot, 1):.0%}；法义逐段纪要另按相关度节选，不计此）")
    if bad:
        print(f"\n✗ {bad} 项须修（漏触发/死触发/废止无取代）")
        sys.exit(1)
    print("\n✓ 无漏触发/死触发/废止无取代")


if __name__ == "__main__":
    main()
