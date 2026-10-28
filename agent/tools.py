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

# 查词优先级（用户裁定·恒常·防词义飘移）：列表次序＝取义权威次序。
# 多典义项相异时以靠前者为准，余典作旁参。
#   ① 藏汉大辞典（最主要·主辞典） ② 格西曲扎藏文辞典
#   ③ 瑜伽师地论词汇表 ④ 宝性论大疏词汇表  ←（③④原始数据尚未入库；备到即按此位插入）
DICT_DBS = [
    ("藏汉大辞典", ROOT / "data/processed/dict.sqlite"),
    ("格西曲扎", ROOT / "data/processed/gexi.sqlite"),
    ("瑜伽师地论词汇表", ROOT / "data/processed/yogacarabhumi_glossary.sqlite"),  # ③
    ("宝性论大疏词汇表", ROOT / "data/processed/ratnagotra_glossary.sqlite"),      # ④(≠tm_baoxinglun译例)
]
# 词源→优先级序号（越小越权威），供 lookup_dict 结果排序，保证主辞典恒居首。
# 键用「数据库 entries.source 的实际值」（非 DICT_DBS 标签），否则对不上。
# 用户裁定次序：藏汉大辞典＞格西曲扎藏文词典＞〔瑜伽师地论词汇表＞宝性论大疏词汇表·待入库〕。
# 「甘肃版藏汉词典」(与藏汉大辞典同库的另一部)未在用户次序内，暂置于已命名诸典之后(默认·待确认)；
# 未列出的词源(含空 source)一律落末，组内保持原检索序(稳定排序)。
_DICT_SOURCE_ORDER = [
    "藏汉大辞典",
    "格西曲扎藏文词典",
    "瑜伽师地论词汇表",        # ③(entries.source 实际值)
    "宝性论大疏词汇表",        # ④(entries.source 实际值)
    "甘肃版藏汉词典",          # 用户次序外·暂置名列诸典之后
]
DICT_PRIORITY = {name: i for i, name in enumerate(_DICT_SOURCE_ORDER)}
_DICT_PRIORITY_FALLBACK = len(_DICT_SOURCE_ORDER)
# ========== 多项目：共享底座 + 分项目层 ==========
# 词典(DICT_DBS)与流水线代码 = 两项目共享。
# 术语库/翻译记忆/笔记 = 「共享基础 + 项目覆盖」：新项目(如时轮)复用胜乘中观积累的
# 术语知识(只读共享 glossary)，但各自的译例/笔记/新增术语互不写入、互不污染。
SHARED_GLOSSARY = ROOT / "glossary/glossary.tsv"   # 共享基础术语库（人工核心资产·进仓库）

# 译例（翻译记忆）：自动扫描 data/processed/tm_gzhanstong_*.jsonl（回流即生效，无需手工登记）；
# 各段要点摘要原为此处行内注释，已迁至 docs/tm_index.md。末附两份底本样例译例。
_GZHANSTONG_TM = sorted((ROOT / "data/processed").glob("tm_gzhanstong_*.jsonl")) + [
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
    # 按查词优先级稳定排序：主辞典（藏汉大辞典）义项恒居首，余典依次旁参（防飘移）。
    results.sort(key=lambda r: DICT_PRIORITY.get(r["source"], _DICT_PRIORITY_FALLBACK))
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
        # 覆盖层出现的藏文词，整组替换基础层同词条目（项目专用译名优先），故新项目既复用
        # 积累术语，又能就本项目语境改写而不影响共享库。
        groups = {}   # bo -> [GlossEntry…]（同层内按文件行序，越后越新）
        seq = 0
        for gf in _cfg()["glossary"]:
            if not gf.exists():
                continue
            is_overlay = gf != SHARED_GLOSSARY
            fresh = set()
            for i, line in enumerate(gf.read_text(encoding="utf-8").splitlines()):
                if i == 0:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                try:
                    freq = int(parts[2])
                except ValueError:
                    continue
                bo, zh = parts[0], parts[1]
                src = parts[3] if len(parts) >= 4 else ""
                if is_overlay and bo not in fresh:      # 覆盖层：首次出现即清空基础层同词
                    groups[bo] = []
                    fresh.add(bo)
                seq += 1
                groups.setdefault(bo, []).append(_gloss_entry(zh, freq, src, seq))
        resolved = ((bo, _resolve_gloss(es)) for bo, es in groups.items() if es)
        _glossary_cache = {bo: v for bo, v in resolved if v is not None}
    return _glossary_cache


# ---------- 术语择优（用户裁定·恒常）----------
# 权威分层：用户裁定/校订本(3) ＞ 人工校正(2) ＞ 自动抽取(1)；「参考」标记(0)＝降级不强制。
# 曾只认「人工校正」字样，致「用户裁定」「校订本(用户认可)」条目被频次高的自动条目静默盖掉
# （45 条失效：等无间缘→无间缘、承许→欲、意趣→深密、归摄→集会…），今改分层择优。
_CTX_MARK = ("语境", "按境")
_CORE_CUT = re.compile(r"[（(〔\[;；·｜]")


class GlossEntry(tuple):
    __slots__ = ()
    zh = property(lambda s: s[0]); freq = property(lambda s: s[1])
    tier = property(lambda s: s[2]); multi = property(lambda s: s[3])
    ctx = property(lambda s: s[4]); seq = property(lambda s: s[5])
    core = property(lambda s: s[6])


def _gloss_entry(zh: str, freq: int, src: str, seq: int) -> GlossEntry:
    if "参考" in src:
        tier = 0
    elif "用户" in src or "校订本" in src:
        tier = 3
    elif "人工校正" in src:
        tier = 2
    else:
        tier = 1
    core = _CORE_CUT.split(zh, 1)[0].strip() or zh.strip()
    return GlossEntry((zh, freq, tier, "多义" in src, any(m in zh for m in _CTX_MARK), seq, core))


def _resolve_gloss(es):
    """同一藏文词头的多条 → (汉译, 频次, 是否多义)。见上方分层规则。"""
    rank = lambda e: (e.tier, e.freq, e.seq)
    best = max(es, key=rank)
    freq = max(e.freq for e in es)
    cores = {e.core for e in es}
    if best.multi:                                   # 旧式显式「多义」条目，自带义项清单
        return best.zh, freq, True
    if best.tier == 0:                               # 只剩降级「参考」条目（校正命中率低）→不进资料包，
        return None                                  # 交由词典＋译例供义，免低命中译名继续误导
    if len(cores) == 1:                              # 只有一个核心译名→强制
        return best.zh, freq, False
    if best.tier == 1:                               # 纯自动条目间冲突→沿旧规取频次最高强制
        return best.zh, freq, False
    top = [e for e in es if e.tier == best.tier]
    if len({e.core for e in top}) == 1 and not any(e.ctx for e in top):
        return best.zh, freq, False                  # 最高层单一定名→取代低层（替换型纠正）
    # 多义：列出全部核心义项，高层在前；每义附判别线索（截短）
    seen, senses = set(), []
    for e in sorted(es, key=rank, reverse=True):
        if e.core in seen or e.tier == 0:
            continue
        seen.add(e.core)
        senses.append(e.zh if len(e.zh) <= 90 else e.zh[:88] + "…")
    return "｜".join(senses), freq, True


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
