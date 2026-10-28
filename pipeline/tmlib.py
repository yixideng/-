"""译例（翻译记忆）登记约定：由平行文文件名自动派生 tm 文件名与出处标签。

平行文命名                                  → 译例文件
review/gzhanstong_6.10_<题>_parallel.txt     → data/processed/tm_gzhanstong_610.jsonl
review/gzhanstong_5.13a_<题>_parallel.txt    → tm_gzhanstong_513a.jsonl
review/gzhanstong_2.0_parallel.txt           → tm_gzhanstong_2.jsonl（「.0」省去）
review/gzhanstong_reviewed_parallel.txt      → tm_gzhanstong_reviewed.jsonl
projects/kalacakra/review/kalacakra_46_<题>_parallel.txt → tm_kalacakra_46.jsonl

tools.py 按文件名通配自动加载，故回流只需对齐出 tm 文件即生效，无需手工登记。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
ALIGN = ROOT / "pipeline/align.py"

PROJECTS = {
    "gzhanstong": {"review": ROOT / "review", "glob": "gzhanstong_*.txt",
                   "prefix": "gzhanstong", "label": "他空中观"},
    "kalacakra": {"review": ROOT / "projects/kalacakra/review", "glob": "kalacakra_*_parallel.txt",
                  "prefix": "kalacakra", "label": "时轮根本续"},
}
_PIN = {"2": "品二", "3": "品三", "4": "品四", "5": "品五", "6": "品六", "7": "品七", "8": "品八"}


def parallels(project: str):
    cfg = PROJECTS[project]
    return sorted(p for p in cfg["review"].glob(cfg["glob"]) if p.suffix == ".txt")


def _parts(path: Path, project: str):
    prefix = PROJECTS[project]["prefix"]
    stem = re.sub(r"_parallel$", "", path.stem)
    rest = stem[len(prefix) + 1:] if stem.startswith(prefix + "_") else stem
    sec, _, title = rest.partition("_")
    return sec, title


def tm_id(path: Path, project: str = "gzhanstong") -> str:
    sec, _ = _parts(Path(path), project)
    if sec.endswith(".0"):
        sec = sec[:-2]
    return sec.replace(".", "")


def tm_path(path: Path, project: str = "gzhanstong") -> Path:
    return PROCESSED / f"tm_{PROJECTS[project]['prefix']}_{tm_id(path, project)}.jsonl"


def source_label(path: Path, project: str = "gzhanstong") -> str:
    sec, title = _parts(Path(path), project)
    base = PROJECTS[project]["label"]
    if sec == "reviewed":
        return f"{base}校订本(用户认可·文风范本)"
    pin = _PIN.get(sec[:1], "") if project == "gzhanstong" else ""
    return f"{base}{pin}{sec}{title}校订本(用户认可·文风范本)"


def align_one(path: Path, project: str = "gzhanstong", quiet: bool = False) -> Path:
    out = tm_path(path, project)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(ALIGN), str(path), "--source",
                        source_label(path, project), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"对齐失败 {path.name}: {r.stderr.strip()[:300]}")
    if not quiet:
        print(r.stdout.strip())
    return out
