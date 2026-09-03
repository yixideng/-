"""Agent 检索工具三件套：查词典 / 查术语表 / 查翻译记忆。

被 translator.py 调用；也可单独 import 使用。
所有输入藏文自动经 normalize 归一后再查。
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from normalize import lookup_key, nfc  # noqa: E402

DICT_DBS = [
    ("藏汉大辞典", ROOT / "data/processed/dict.sqlite"),
    ("格西曲扎", ROOT / "data/processed/gexi.sqlite"),
]
# ========== 多项目：共享底座 + 分项目层 ==========
# 词典(DICT_DBS)与流水线代码 = 两项目共享。
# 术语库/翻译记忆/笔记 = 「共享基础 + 项目覆盖」：新项目(如时轮)复用胜乘中观积累的
# 术语知识(只读共享 glossary)，但各自的译例/笔记/新增术语互不写入、互不污染。
SHARED_GLOSSARY = ROOT / "glossary/glossary.tsv"   # 共享基础术语库（人工核心资产·进仓库）

_GZHANSTONG_TM = [
    ROOT / "data/processed/tm_gzhanstong_reviewed.jsonl",  # 用户校订·文风范本，优先
    ROOT / "data/processed/tm_gzhanstong_2.jsonl",         # 同上（2.0 论体）
    ROOT / "data/processed/tm_gzhanstong_22.jsonl",        # 同上（2.2 广说）
    ROOT / "data/processed/tm_gzhanstong_23.jsonl",        # 同上（2.3 中观异门）
    ROOT / "data/processed/tm_gzhanstong_24.jsonl",        # 同上（品二 蕴界处）
    ROOT / "data/processed/tm_gzhanstong_25.jsonl",        # 同上（品二 行蕴）
    ROOT / "data/processed/tm_gzhanstong_26.jsonl",        # 同上（品二 性相法）
    ROOT / "data/processed/tm_gzhanstong_27.jsonl",        # 同上（品二 假立法续）
    ROOT / "data/processed/tm_gzhanstong_28.jsonl",        # 同上（品二 无实法与道）
    ROOT / "data/processed/tm_gzhanstong_29.jsonl",        # 同上（品二 五乘/无为/廿五有/果）
    ROOT / "data/processed/tm_gzhanstong_210.jsonl",       # 同上（品二 观察所知五基）
    ROOT / "data/processed/tm_gzhanstong_211.jsonl",       # 同上（品二 观察四谛/苦集道灭·细微集谛）
    ROOT / "data/processed/tm_gzhanstong_212.jsonl",       # 同上（品二末 分别无分别四门·胜义四谛皆法身相·果末）
    ROOT / "data/processed/tm_gzhanstong_32.jsonl",        # 同上（品三 界之常义·周遍义）
    ROOT / "data/processed/tm_gzhanstong_33.jsonl",        # 同上（品三 界之觉义·一切相·自性涅槃）
    ROOT / "data/processed/tm_gzhanstong_34.jsonl",        # 同上（品三 界之一切相义·离戏相·不相杂相·三喻四根颂）
    ROOT / "data/processed/tm_gzhanstong_35.jsonl",        # 同上（品三 双运相·种姓与界·龙树会通·九相总摄·五根颂）
    ROOT / "data/processed/tm_gzhanstong_36.jsonl",        # 同上（品三 九相断疑·常义/周遍义/自证义·三根颂）
    ROOT / "data/processed/tm_gzhanstong_37.jsonl",        # 同上（品三 破立归属·缘起断疑·双运义·种界现相·凡圣见·多根颂）
    ROOT / "data/processed/tm_gzhanstong_38.jsonl",        # 同上（品三 法界离时非相续·种界khams/rigs遍义·佛遍非支分·日云障喻·破三错解如来藏·六根颂）
    ROOT / "data/processed/tm_gzhanstong_39.jsonl",        # 同上（品三终 二谛判属·遍基智/阿赖耶智·涅槃基与轮回基·种性觉未觉·果非新生·谤敬果报·多根颂）
    ROOT / "data/processed/tm_gzhanstong_41.jsonl",        # 同上（品四开篇 真世俗唯识·八识聚·世亲三十颂略标·二我增益·三能变·根颂）
    ROOT / "data/processed/tm_gzhanstong_42.jsonl",        # 同上（品四 三识体性·异熟分/种子分·阿赖耶三相·恒河浪喻·七识如波·六根颂）
    ROOT / "data/processed/tm_gzhanstong_43.jsonl",        # 同上（品四 教证安立·心意识三名训诂·取识住识三分·五遍行·无覆无记·如河·转依大圆镜智）
    ROOT / "data/processed/tm_gzhanstong_44.jsonl",        # 同上（品四 释末那·六转识·八识俱起如波·意识界限五位·多根颂）
    ROOT / "data/processed/tm_gzhanstong_45.jsonl",        # 同上（品四 因果次第·二取·教理成立阿赖耶·引阿毗达磨经/解深密经·阿陀那识）
    ROOT / "data/processed/tm_gzhanstong_46.jsonl",        # 同上（品四 理证成立阿赖耶·衣罩喻[如来藏借名指阿赖耶识]·二取还灭·唯识无外境·心性本净白布喻·引密严经月星乳酪喻·犊子部意识粗依）
    ROOT / "data/processed/tm_gzhanstong_47.jsonl",        # 同上（品四 外境不成破经部授相·乳酪种芽功德喻[果为因之功德=同一相续转变]·十八部阿赖耶异名[大众部根本识/化地部穷生死蕴/正量红衣异熟识/上座部有分识bhavāṅga]·龙树菩提心释成立阿赖耶）
    ROOT / "data/processed/tm_gzhanstong_48.jsonl",        # 同上（品四 理证成立阿赖耶·9根颂+疏·异生烦恼种依→阿罗汉相违·种依唯阿赖耶·入胎羯罗蓝位识非意识·四无心位[闷绝/灭尽定/无想定/熟睡]有心·破命根说[命根=假立有]·灭尽定近取因·破四大灭心同顺世派）
    ROOT / "data/processed/tm_zhongguan.jsonl",
    ROOT / "data/processed/tm_baoxinglun.jsonl",
]

PROJECTS = {
    # 胜乘中观(他空大中观)——默认项目，沿用现有 notes/ review/ glossary/ 与 tm_gzhanstong_*
    "gzhanstong": {
        "name": "胜乘中观(他空大中观)",
        "glossary": [SHARED_GLOSSARY],
        "tm": _GZHANSTONG_TM,
        "notes": [ROOT / "notes/法义.md", ROOT / "notes/句法.md", ROOT / "notes/文风.md"],
        "review": ROOT / "review",
    },
    # 时轮根本续——独立笔记/译例/术语覆盖层；共享 SHARED_GLOSSARY(只读)与两本词典
    "kalacakra": {
        "name": "时轮根本续(Kālacakra)",
        "glossary": [SHARED_GLOSSARY,                       # 共享基础(只读)——复用积累术语
                     ROOT / "projects/kalacakra/glossary.tsv"],  # 时轮术语覆盖层(时轮专用·优先)
        "tm": sorted((ROOT / "data/processed").glob("tm_kalacakra_*.jsonl")),
        "notes": [ROOT / "projects/kalacakra/notes/法义.md",
                  ROOT / "projects/kalacakra/notes/句法.md",
                  ROOT / "projects/kalacakra/notes/文风.md"],
        "review": ROOT / "projects/kalacakra/review",
    },
}

PROJECT = "gzhanstong"   # 当前项目；translator.py 依 --project 设定；默认胜乘中观(不影响原有行为)


def set_project(name: str):
    """切换当前项目并清检索缓存。未知项目直接报错。"""
    global PROJECT, _glossary_cache, _tm_cache
    if name not in PROJECTS:
        raise SystemExit(f"未知项目：{name}；可选 {list(PROJECTS)}")
    PROJECT = name
    _glossary_cache = None
    _tm_cache = None


def _cfg():
    return PROJECTS[PROJECT]


def project_notes():
    """当前项目的笔记层文件（供 translator 注入）。"""
    return _cfg()["notes"]


# 向后兼容别名（旧引用仍可用；实际加载走 _cfg()）
GLOSSARY = SHARED_GLOSSARY
TM_FILES = _GZHANSTONG_TM

# 常见格助词/接续，剥离后重查（简单形态还原）
CASE_SUFFIXES = ["འི", "ར", "ས", "འམ", "འང", "ཀྱི", "གྱི", "གི", "ཡི",
                 "ཀྱིས", "གྱིས", "གིས", "ཡིས", "ཏུ", "དུ", "སུ", "ལ", "ན"]

# 黏着于末音节（无 tsheg 分隔）的格助词：如 སྟོང་པ+འི=སྟོང་པའི、ངོ་བོ+ས=ངོ་བོས、
# དོན་དམ་པ+ར=དོན་དམ་པར。分隔式格助词（གྱི/ཀྱི/ལ/ན…自成音节）由「取更短窗口」处理，
# 不在此列。扫描术语表时，整词未命中则剥掉末音节的黏着格助词重试一次。
GLUED_SUFFIXES = ["འིའོ", "འི", "འམ", "འང", "ས", "ར"]


def _stem_glued(syls):
    """若末音节带黏着格助词，返回剥离后的音节列表（长度不变，末节变短）；否则 None。"""
    last = syls[-1]
    for suf in GLUED_SUFFIXES:
        if last.endswith(suf) and len(last) > len(suf):
            return syls[:-1] + [last[: -len(suf)]]
    return None


def syllables(bo: str):
    return [s for s in re.split(r"[་།༎\s]+", nfc(bo)) if s]


# ---------- 词典 ----------

def _query_db(db: Path, key: str):
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT headword, source, page, pos, senses FROM entries WHERE headword=?",
        (key,)).fetchall()
    if not rows:
        alt = con.execute("SELECT headword FROM alt_map WHERE alt=?", (key,)).fetchone()
        if alt:
            rows = con.execute(
                "SELECT headword, source, page, pos, senses FROM entries WHERE headword=?",
                (alt[0],)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def lookup_dict(word: str, compact=True):
    """查两本词典。查不到时剥格助词重试。返回 [{headword,source,senses...}]"""
    key = lookup_key(word)
    results = []
    for _, db in DICT_DBS:
        results += _query_db(db, key)
    if not results:
        for suf in CASE_SUFFIXES:
            if key.endswith(suf) and len(key) > len(suf):
                stem = key[: -len(suf)].rstrip("་")
                for _, db in DICT_DBS:
                    results += _query_db(db, stem)
                if results:
                    break
    if compact:
        for r in results:
            senses = json.loads(r["senses"])
            r["senses"] = [s[:120] for s in senses[:4]]
    return results


# ---------- 术语表 ----------

_glossary_cache = None


def load_glossary():
    """返回 {藏文: (汉译, 频次, 是否多义)}。

    出处列含「多义」者：该词依语境分义，汉译列以「｜」分隔各义项及判别线索，
    翻译时**不强制**，只作提示。其余为强制统一的规范译名。
    人工校正条目永远优先于机器抽取。
    """
    global _glossary_cache
    if _glossary_cache is None:
        # 依当前项目按序读取术语文件：共享基础在前、项目覆盖层在后；
        # 覆盖层同一藏文词直接盖过基础层（项目专用译名优先），故新项目既复用
        # 积累术语，又能就本项目语境改写而不影响共享库。
        merged = {}  # bo -> (zh, freq, human, multi)
        for gf in _cfg()["glossary"]:
            if not gf.exists():
                continue
            is_overlay = gf != SHARED_GLOSSARY
            for i, line in enumerate(gf.open(encoding="utf-8")):
                if i == 0:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    bo, zh, freq = parts[0], parts[1], int(parts[2])
                    src = parts[3] if len(parts) >= 4 else ""
                    human = "人工校正" in src
                    multi = "多义" in src
                    prev = merged.get(bo)
                    # 覆盖层无条件盖过基础层；同层内按 多义>人工校正>频次 择优
                    if is_overlay or prev is None or (multi and not prev[3]) \
                            or (multi == prev[3] and human and not prev[2]) \
                            or (multi == prev[3] and human == prev[2] and freq > prev[1]):
                        merged[bo] = (zh, freq, human, multi)
        _glossary_cache = {k: (v[0], v[1], v[3]) for k, v in merged.items()}
    return _glossary_cache


def scan_glossary(bo_text: str, max_len=8):
    """在一段藏文上最长匹配术语表，返回 [(藏文, 汉译, 频次, 是否多义)]。

    最长匹配优先；整词未命中时，剥掉末音节的黏着格助词（如 འི/ས/ར）再试一次，
    使 སྟོང་པའི→སྟོང་པ、ངོ་བོས→ངོ་བོ、དོན་དམ་པར→དོན་དམ་པ 等带格形也能命中术语约束。
    """
    g = load_glossary()
    syls = syllables(bo_text)
    hits, i, n = [], 0, len(syls)
    while i < n:
        matched, adv = None, 0
        for l in range(min(max_len, n - i), 1, -1):
            win = syls[i:i + l]
            cand = "་".join(win)
            if cand in g:                       # 原形命中
                matched, adv = cand, l
                break
            stem = _stem_glued(win)             # 末音节剥格助词后命中
            if stem is not None:
                scand = "་".join(stem)
                if scand in g:
                    matched, adv = scand, l     # 消费原始 l 个音节（含格助词）
                    break
        if matched:
            zh, freq, multi = g[matched]
            hits.append((matched, zh, freq, multi))
            i += adv
        else:
            i += 1
    # 去重保序
    seen, out = set(), []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            out.append(h)
    return out


# ---------- 翻译记忆 ----------

_tm_cache = None


def load_tm():
    global _tm_cache
    if _tm_cache is None:
        segs = []
        for p in _cfg()["tm"]:            # 当前项目的翻译记忆（各项目独立，互不检索）
            if p.exists():
                for line in p.open(encoding="utf-8"):
                    s = json.loads(line)
                    if s.get("bo") and s.get("zh"):
                        s["_syls"] = set(syllables(s["bo"]))
                        segs.append(s)
        _tm_cache = segs
    return _tm_cache


def search_tm(bo_text: str, k=3):
    """按音节 Jaccard 相似度检索最像的历史译例。数据量小，线性扫即可。"""
    q = set(syllables(bo_text))
    if not q:
        return []
    scored = []
    for s in load_tm():
        inter = len(q & s["_syls"])
        if inter < 2:
            continue
        score = inter / len(q | s["_syls"])
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [{"score": round(sc, 3), "bo": s["bo"][:200], "zh": s["zh"][:200],
             "source": s["source"]} for sc, s in scored[:k]]
