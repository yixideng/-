"""一键重建全部可再生数据（容器是临时的，新会话开工先跑这一条）。

    python3 pipeline/rebuild.py            # 缺什么补什么（已有的跳过）
    python3 pipeline/rebuild.py --force    # 全部重下重建
    python3 pipeline/rebuild.py --tm-only  # 只重对齐译例（改了平行文后）

做三件事：
  1. 四部字典：从 GitHub Release 下载原始素材 → 解析 → 建 sqlite
     （查词优先级：藏汉大辞典＞格西曲扎＞瑜伽师地论词汇表＞宝性论大疏词汇表，见 agent/tools.py）
  2. 两份底本样例译例：Release 下载 → 对齐
  3. 全部用户校正版平行文（review/ 与各项目 review/）→ 对齐为译例；
     并清掉已无对应平行文的陈旧 tm 文件，免重复检索。
下载需环境变量 GITHUB_TOKEN（云端会话自带；本机自行生成，见 CLAUDE.md）。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmlib  # noqa: E402

ROOT = tmlib.ROOT
P = ROOT / "pipeline"
RAW_D = ROOT / "data/raw/dictionaries"
RAW_P = ROOT / "data/raw/parallel"
PROC = tmlib.PROCESSED
REPO = "yixideng/-"

# (名称, Release asset id, 原始文件, 解析命令(原始→jsonl), jsonl, sqlite)
DICTS = [
    ("藏汉大辞典", 488012632, RAW_D / "zhdcd_full.txt",
     lambda raw, js: [P / "parse_dict.py", raw, "--out", js], PROC / "dict.jsonl", PROC / "dict.sqlite"),
    ("格西曲扎藏文词典", 488022264, RAW_D / "gexi_full.txt",
     lambda raw, js: [P / "parse_gexi.py", raw, "--out", js], PROC / "gexi.jsonl", PROC / "gexi.sqlite"),
    ("瑜伽师地论词汇表", 681735943, RAW_D / "yogacarabhumi_glossary_mdx.txt",
     lambda raw, js: [P / "parse_mdx_glossary.py", raw, "--source", "瑜伽师地论词汇表", "--out", js],
     PROC / "yogacarabhumi_glossary.jsonl", PROC / "yogacarabhumi_glossary.sqlite"),
    ("宝性论大疏词汇表", 681709400, RAW_D / "ratnagotra_glossary_mdx.txt",
     lambda raw, js: [P / "parse_mdx_glossary.py", raw, "--source", "宝性论大疏词汇表", "--out", js],
     PROC / "ratnagotra_glossary.jsonl", PROC / "ratnagotra_glossary.sqlite"),
]
# (Release asset id, 原始文件, 出处标签, 译例文件)
SAMPLES = [
    (488042512, RAW_P / "sample1_baoxinglun.txt", "宝性论大疏", PROC / "tm_baoxinglun.jsonl"),
    (488043677, RAW_P / "sample2_zhongguan.txt", "极广胜乘中观决定", PROC / "tm_zhongguan.jsonl"),
]


def run(args):
    r = subprocess.run([sys.executable] + [str(a) for a in args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"失败: {' '.join(map(str, args))}\n{r.stderr.strip()[:500]}")
    return r.stdout.strip()


def download(asset_id: int, dest: Path, force: bool):
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("缺 GITHUB_TOKEN 环境变量，无法从 Release 下载（见 CLAUDE.md「GITHUB_TOKEN」）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}"
    r = subprocess.run(["curl", "-sSLf", "-H", f"Authorization: Bearer {token}",
                        "-H", "Accept: application/octet-stream", url, "-o", str(dest)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        sys.exit(f"下载失败 asset {asset_id} → {dest.name}: {r.stderr.strip()[:300]}")
    print(f"  下载 {dest.name}（{dest.stat().st_size / 1048576:.1f} MB）")


def build_dicts(force: bool):
    print("① 字典")
    for name, aid, raw, parse, js, db in DICTS:
        if db.exists() and not force:
            print(f"  {name}：已在，跳过")
            continue
        download(aid, raw, force)
        print("  " + run(parse(raw, js)).splitlines()[-1])
        print("  " + run([P / "build_index.py", js, "--out", db]).splitlines()[-1])


def build_samples(force: bool):
    print("② 底本样例译例")
    for aid, raw, label, out in SAMPLES:
        if out.exists() and not force:
            print(f"  {out.name}：已在，跳过")
            continue
        download(aid, raw, force)
        print("  " + run([P / "align.py", raw, "--source", label, "--out", out]).splitlines()[-1])


def build_tm():
    print("③ 用户校正版平行文 → 译例")
    for project, cfg in tmlib.PROJECTS.items():
        produced = set()
        for p in tmlib.parallels(project):
            produced.add(tmlib.align_one(p, project, quiet=True).name)
        stale = [f for f in PROC.glob(f"tm_{cfg['prefix']}_*.jsonl") if f.name not in produced]
        for f in stale:
            f.unlink()
        print(f"  {project}：{len(produced)} 份平行文已对齐" + (f"；清除陈旧 tm {len(stale)} 个" if stale else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="全部重下重建")
    ap.add_argument("--tm-only", action="store_true", help="只重对齐译例")
    a = ap.parse_args()
    if not a.tm_only:
        build_dicts(a.force)
        build_samples(a.force)
    build_tm()
    print("完成。")


if __name__ == "__main__":
    main()
