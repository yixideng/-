"""从完整词典文件均匀抽样，生成小体量样本供格式核对。

样本按 </> 记录数在全书范围内等距抽取，覆盖各字头；额外强制纳入
开头与结尾若干条（这些位置最容易有特殊格式）。输出保留 </> 分隔符，
可直接交给 parse_dict.py 解析。

用法：
    python pipeline/make_sample.py 你的词典.txt \
        --out data/raw/dictionaries/sample_full.html --n 300
"""
import argparse
from pathlib import Path

SEP = "</>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/raw/dictionaries/sample_full.html"))
    ap.add_argument("--n", type=int, default=300, help="抽样条数")
    ap.add_argument("--edge", type=int, default=10, help="强制纳入的首尾条数")
    args = ap.parse_args()

    text = args.input.read_text(encoding="utf-8", errors="replace")
    records = [r for r in text.split(SEP) if "<p" in r]
    total = len(records)
    print(f"全书共 {total} 条记录")

    if total <= args.n:
        picked = list(range(total))
    else:
        idx = set()
        # 首尾强制纳入
        idx.update(range(min(args.edge, total)))
        idx.update(range(max(0, total - args.edge), total))
        # 中间等距抽取
        stride = total / (args.n - len(idx))
        i = 0.0
        while i < total and len(idx) < args.n:
            idx.add(int(i))
            i += stride
        picked = sorted(idx)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for i in picked:
            f.write(records[i].strip())
            f.write("\n" + SEP + "\n")

    size_kb = args.out.stat().st_size / 1024
    print(f"抽样 {len(picked)} 条 -> {args.out}（{size_kb:.0f} KB）")
    print("接着可运行：")
    print(f"  python3 pipeline/parse_dict.py {args.out} "
          f"--out data/processed/sample_full.jsonl --stats")


if __name__ == "__main__":
    main()
