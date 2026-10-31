"""藏译汉流水线主程序。

流程：输入藏文 → 分段 → 检索（术语表/词典/翻译记忆）→ 组装翻译资料包
     → 交给 Claude 翻译（或 --packet 只输出资料包）。

用法：
    # 只生成资料包（不调用模型，便于检查检索质量）
    python agent/translator.py --text "བྱང་ཆུབ་སེམས་..." --packet

    # 完整翻译（经 claude CLI 调用模型）
    python agent/translator.py --file input.txt
    python agent/translator.py --text "..." --out result.md
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
import tools  # noqa: E402

# 单字虚词停用表：逐字兜底查词典时跳过这些语法词（格助词/接续/终结/名物化等），
# 免得把 ནི/དང/ཀྱི/ལ… 也堆进「逐字参考」。实词（如 ཡོངས/དཔྱོད）不在此列，照查。
PARTICLE_SYLS = {
    "ནི", "དང", "ཀྱི", "གྱི", "གི", "ཡི", "ཀྱིས", "གྱིས", "གིས", "ཡིས",
    "ལ", "ན", "ཏུ", "དུ", "སུ", "རུ", "ར", "ས", "འི", "འམ", "འང", "འོ",
    "སྟེ", "ཏེ", "དེ", "ཅིང", "ཤིང", "ཞིང", "ཅེས", "ཞེས", "ཅེ", "ཞེ",
    "པ", "བ", "པོ", "བོ", "མོ", "གོ", "ཏོ", "དོ", "ནོ", "རོ", "སོ", "ལོ",
    "ཡང", "ཀྱང", "ནས", "ལས", "ཞིག", "ཅིག", "ཤིག", "གང", "པར", "བར", "པའི", "བའི",
}

PROMPT_FILE = ROOT / "agent/prompts/translate.md"
# 笔记层（恒常注入）：法义纲要在前（先立框架），句法通则次之，文风通则在后。
# 具体文件按当前项目取（tools.project_notes()）；默认项目 gzhanstong 即 notes/ 三件。
POLISH_FILE = ROOT / "agent/prompts/polish.md"


# 藏文终结词（rdzogs tshig / slar bsdu）：句子真正说完的标志（≈句号）。
# 一 shad 分句若以下列音节收尾（或以 འོ 收尾，如 པའོ/བའོ/ཟིན་ཏོའོ…），即视为句末。
# 而 དང༌/ཞིང/ཏེ/ལ/ཕྱིར/ལྟར… 等只是句内接续，不算句末——故不会在其后腰斩。
TERMINATIVES = {"ནོ", "བོ", "ཏོ", "དོ", "རོ", "སོ", "ངོ", "གོ", "མོ", "ལོ", "འོ"}


def _shad_clauses(block: str):
    """把一段按 shad 切成分句；双 shad「། །」的第二个 shad 会甩到下句开头，剥掉。"""
    parts = [p.strip().lstrip("།༎ ").strip()
             for p in re.split(r"(?<=[།༎])", block)]
    return [p for p in parts if p]


def _sentence_end(clause: str) -> bool:
    """该 shad 分句是否以终结词收尾（即整句已说完）。"""
    syls = [s for s in re.split(r"[་༌\s]+", clause.rstrip("།༎ ")) if s]
    return bool(syls) and (syls[-1] in TERMINATIVES or syls[-1].endswith("འོ"))


# 引语标记：终结词后紧跟这些（「…བདེའོ། །…ལོ། །སྙམ་དུ」「…ནོ། །ཞེས」），引语未完，不算句末
_QUOTE_HEAD = re.compile(r"^(ཞེས|ཅེས|ཤེས|སྙམ|ཟེར)")
# 科判标题：序数开头（དང་པོ/གཉིས་པ…/དོན་ཚན་X་པ），领起一科；「X་པ་ལྟར་ན」（若如第X者）不算
_ORDINAL = r"(དང་པོ|གཉིས་པ|གསུམ་པ|བཞི་པ|ལྔ་པ|དྲུག་པ|བདུན་པ|བརྒྱད་པ|དགུ་པ|བཅུ་པ|དོན་ཚན་\S+?་པ)"
_HEAD_START = re.compile(r"^" + _ORDINAL + r"(?!་ལྟར)")
_HEAD_END = re.compile(r"(ནི|ལ|ལས)།$")


def _is_heading(sent) -> bool:
    """一组分句是否为科判标题句：首分句序数开头、末分句以 ནི།/ལ།/ལས། 收、且无终结词（不含论述）。"""
    return bool(sent) and bool(_HEAD_START.match(sent[0])) and bool(_HEAD_END.search(sent[-1])) \
        and not any(_sentence_end(c) for c in sent) and len(sent) <= 4


def split_segments(text: str, max_shad=16):
    """分段：**以原文自然段（换行）为单位，一段=一组对照**。
    单段整体保留（含段内「…ཡིན་ནོ། །ཞེས་པ…པའོ།」这类中途句号＋收束句），
    不因段内的句号而拆——与用户校订本「根颂／释论各自成组」的排版一致。

    仅当某自然段超长（shad 分句数 > max_shad）时，才兜底断开，
    且**只断在句末终结词处**（rdzogs tshig，绝不腰斩）。无换行的整块输入
    （如直接粘贴的一大段）亦按同规则：先整体，超长再按句末断。

    max_shad 取 16 的权衡：≤16 分句的自然段（如画师喻 15、灯喻 16）整段保留，
    保证直译逐句对应；而 19/25/50 分句这类超长段会在句界切成 ~16 分句的小组，
    避免过长导致翻译从「直译」向「意译」飘移——切点仍是完整句，不伤对照。

    旧版按固定 shad 数硬切，会把『…གཞི་བྱེད་པའི་ཕྱིར། │ སྣོད་དང་མཚུངས་པ་ཡིན…སོ།』
    在 ཕྱིར 处腰斩，谓语「与器相似」被甩到下段成残句；故彻底改为自然段优先。"""
    segs = []
    # 原文换行是作者给的自然段边界，优先采信；无换行则整体为一块
    blocks = [b.strip() for b in text.splitlines() if b.strip()] or [text]
    carry = []                                # 上段末尾的科判标题，挪到本段开头（标题领起其下正文）
    for block in blocks:
        parts = carry + _shad_clauses(block)
        carry = []
        # 先切整句：句末＝终结词收尾且下一分句不是引语续接（「…ལོ། །སྙམ་དུ」「…ནོ། །ཞེས」）；
        # 科判标题（序数开头）前亦断句，使标题自成一句、领起其后。
        sentences, cur = [], []
        for i, p in enumerate(parts):
            if cur and _HEAD_START.match(p) and (_sentence_end(cur[-1]) or _is_heading(cur)):
                sentences.append(cur)
                cur = []
            cur.append(p)
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            if _sentence_end(p) and not _QUOTE_HEAD.match(nxt):
                sentences.append(cur)
                cur = []
        if cur:                               # 末尾无终结词的残句自成一句
            sentences.append(cur)
        if len(sentences) > 1 and _is_heading(sentences[-1]) and block is not blocks[-1]:
            carry = sentences.pop()           # 段末悬空的科判标题 → 下一段开头
        n = sum(len(x) for x in sentences)
        if n <= max_shad:                     # 常态：自然段整体成一组（不因段内句号而拆）
            if sentences:
                segs.append(" ".join(c for x in sentences for c in x))
            continue
        # 超长段兜底：把整句贪心打包成 ≤max_shad 的组；断点总在真实句界（不腰斩、不切引语），
        # 遇科判标题句另起一组（标题领起其下论述，与校正版按科分段一致）。单句超长则整句保留。
        group = []
        for sent in sentences:
            if group and (len(group) + len(sent) > max_shad or _is_heading(sent)):
                segs.append(" ".join(group))
                group = []
            group += sent
        if group:
            segs.append(" ".join(group))
    if carry:                                 # 全文末尾的标题（无后续段）自成一组
        segs.append(" ".join(carry))
    return segs


# 笔记节级元数据（写在该节标题下的 HTML 注释里，渲染不可见）：
#   <!-- 触发：A|B|C -->        专项规则：待译藏文含任一触发串才注入；**无此标注＝通则，恒常注入**（拿不准即常驻，最坏等于全量）
#   <!-- 状态：观察 -->          由 diff 归纳、尚未经用户裁定：照常注入，标「观察中」
#   <!-- 状态：废止｜取代：§N --> 已被取代：不注入（原文留档）；须写明取代者，audit_notes.py 校验
_META = re.compile(r"(?m)^<!--\s*(触发|状态)[：:]\s*(.*?)\s*-->")   # 须独占行首（正文里举例的不算）
NOTE_REPORT = []        # 本次各笔记文件的注入报告（打印＋写入质检报告，漏注入可见）


def _sec_meta(sec: str) -> dict:
    meta = {}
    for k, v in _META.findall(sec):
        meta[k] = v
    return meta


def _sec_label(sec: str) -> str:
    """节的简称：§22 / §5.12（法义纪要「## 品五 5.12 …」亦取段号）/ 无编号者取标题前 8 字。"""
    head = sec.splitlines()[0].lstrip("# ").strip()
    m = re.match(r"§?\s*(\d+(?:\.\d+)?[ab]?)", head) or \
        re.match(r"品[一二三四五六七八九十]+\s*(\d+\.\d+[ab]?)", head)
    return ("§" + m.group(1)) if m else head[:8]


def _norm_tsheg(s: str) -> str:
    return s.replace("༌", "་")


def trigger_hit(sec: str, src: str) -> bool:
    trig = _sec_meta(sec).get("触发")
    if not trig:
        return True
    s = _norm_tsheg(src)
    return any(_norm_tsheg(t.strip()) in s for t in trig.split("|") if t.strip())


def gate_sections(body: str, src: str, name: str = ""):
    """笔记节级注入：通则（无触发标注）全量；专项（有触发标注）仅在待译原文含触发串时注入；
    废止节不注入。返回 (注入正文, 报告行)。报告列出跳过的节，令「漏注入」可见、可追查。"""
    secs = re.split(r"(?m)^(?=## )", body)
    keep, fired, skipped, retired, watch = [], [], [], [], []
    for sec in secs:
        meta = _sec_meta(sec)
        lab = _sec_label(sec) if sec.startswith("## ") else ""
        status = meta.get("状态", "")
        if status.startswith("废止"):
            retired.append(lab)
            continue
        if "触发" in meta:
            if not trigger_hit(sec, src):
                skipped.append(lab)
                continue
            fired.append(lab)
        if status.startswith("观察"):
            watch.append(lab)
            sec = re.sub(r"(?m)^(## .*)$", r"\1　〔观察中·未经用户裁定，可酌情〕", sec, count=1)
        keep.append(sec)
    n_always = sum(1 for s in secs if s.startswith("## ") and "触发" not in _sec_meta(s)
                   and not _sec_meta(s).get("状态", "").startswith("废止"))
    rep = f"{name}：常驻 {n_always} 节"
    if fired or skipped:
        rep += f"·专项触发 {len(fired)} 节" + (f"（{' '.join(fired)}）" if fired else "")
        rep += f"·未触发从略 {len(skipped)} 节" + (f"（{' '.join(skipped)}）" if skipped else "")
    if watch:
        rep += f"·观察中 {len(watch)} 节"
    if retired:
        rep += f"·已废止不注入 {len(retired)} 节（{' '.join(retired)}）"
    if skipped:
        keep.append(f"\n> 〔专项规则按触发词注入：本段未触发而从略 {' '.join(skipped)}；全文见 notes/{name}〕\n")
    return "".join(keep), rep


# 「法义.md」逐段纪要标题形如「## 5.22 …」「## 品六 6.10 …」；其余 ## 节为通则。
_FAYI_JY = re.compile(r"## (品[一二三四五六七八九十]+\s*)?\d+\.\d+")


def select_fayi(body: str, src: str, recent: int = 3, related: int = 3) -> str:
    """法义按需注入：通则全量；逐段纪要只取「最近 recent 节（行文连续）＋与待译最相关
    related 节」。相关度＝待译的藏文实词二连音节 ＋ 命中术语之汉译核心词，在纪要中的重合数。
    纪要随翻译逐段增长（品六时已 27 节·3.6 万字），全量注入会稀释规则、拖长资料包。"""
    secs = re.split(r"(?m)^(?=## )", body)
    general = [s for s in secs if not _FAYI_JY.match(s)]
    jy = [(i, s) for i, s in enumerate(secs) if _FAYI_JY.match(s)]
    if len(jy) <= recent + related:
        return body
    syls = [x for x in tools.syllables(src) if x not in PARTICLE_SYLS]
    bigrams = {f"{a}་{b}" for a, b in zip(syls, syls[1:])}
    terms = set()
    for _bo, zh, _f, _m in tools.scan_glossary(src):
        for part in zh.split("｜"):
            core = tools._CORE_CUT.split(part, 1)[0].strip()
            if len(core) >= 2:
                terms.add(core)
    keep = {i for i, _ in jy[-recent:]}
    # 得分按 √篇幅归一，免长节因字多而恒被选中（长节偏置）
    scored = sorted((((sum(b in s for b in bigrams) + 2 * sum(t in s for t in terms))
                      / len(s) ** 0.5, i) for i, s in jy if i not in keep), reverse=True)
    keep |= {i for sc, i in scored[:related] if sc > 0}
    picked = [s for i, s in jy if i in keep]
    note = (f"\n> 〔逐段纪要按需节选：最近 {recent} 节＋相关 {related} 节，共 {len(picked)}/{len(jy)} 节；"
            "全文见 notes/法义.md〕\n\n")
    return "".join(general) + note + "".join(picked)


DICT_MAX = 60      # 词典释义最多列词数（按译例语料罕见度挑难词，非按文中先后截断）
MORPH_MAX = 20


def render_dict_hits(dict_hits):
    """词典释义：命中常达数百词，不能全列（会撑爆资料包），亦不可按文中先后静默截断
    （旧法 dict_hits[:25]：6.12 命中 301 词只列前 25，后文难词如「增一阿含」「卸担」全丢）。
    改按「在已译语料中的出现次数」升序挑最罕见的 DICT_MAX 个——常见词早有译例/术语定译，
    罕见词才最需词典；按原文次序列出，每词一行：主典义 ＋ 余典之简短汉译旁参；从略者明示数目。"""
    if not dict_hits:
        return ["（无词典命中）"]
    corpus = tools.tm_corpus()
    pick = set(w for w, _ in sorted(dict_hits, key=lambda h: corpus.count(h[0]))[:DICT_MAX])
    out = []
    for word, entries in dict_hits:
        if word not in pick:
            continue
        main = entries[0]
        line = f"- {word}〔{main['source']}〕" + "；".join(main["senses"])[:100]
        extra = []
        for e in entries[1:]:
            short = "；".join(e["senses"])
            if e["source"] != main["source"] and len(short) <= 24 and \
                    any(0x4E00 <= ord(c) <= 0x9FFF for c in short):
                extra.append(f"{e['source'][:4]}：{short}")
        if extra:
            line += "｜旁参 " + "｜".join(extra[:2])
        out.append(line)
    if len(dict_hits) > len(pick):
        out.append(f"（另有 {len(dict_hits) - len(pick)} 个较常见词从略——已有译例/术语可循）")
    return out


def build_packet(text: str, missing=None) -> str:
    segs = split_segments(text)
    lines = []
    lines.append(PROMPT_FILE.read_text(encoding="utf-8"))
    if missing:
        lines.append("\n> ⚠ **资料缺失**：" + "；".join(missing) +
                     "。本次词典/译例等可能为空——遇无据之词须在校勘中标明「无词典依据」，勿凭空定名。\n")
    # 笔记层：法义纲要 + 句法通则（先于原文，供全篇遵循）——按当前项目取。
    # 通则恒常注入；专项按触发词注入；法义逐段纪要按相关度节选。注入/从略情况记入 NOTE_REPORT。
    NOTE_REPORT.clear()
    for nf in tools.project_notes():
        if nf.exists():
            body, rep = gate_sections(nf.read_text(encoding="utf-8"), text, nf.name)
            if nf.name == "法义.md":           # 通则全量；逐段纪要按需节选（防提示膨胀稀释规则）
                body = select_fayi(body, text)
                m = re.search(r"共 (\d+/\d+) 节", body)
                if m:
                    rep += f"·逐段纪要节选 {m.group(1)}"
            NOTE_REPORT.append(rep)
            lines.append("\n---\n" + body)
    lines.insert(1, "\n> 〔笔记注入：" + "；".join(NOTE_REPORT) + "〕\n")
    lines.append("\n---\n## 待译原文（共 %d 段）\n" % len(segs))
    for i, s in enumerate(segs, 1):
        lines.append(f"[段{i}] {s}")

    # 术语约束（全篇扫描）
    glo = tools.scan_glossary(text)
    fixed = [g for g in glo if not g[3]]
    multi = [g for g in glo if g[3]]
    lines.append("\n## 术语约束（必须采用的译法）\n")
    if fixed:
        for bo, zh, freq, _ in fixed:
            lines.append(f"- {bo} → **{zh}**（本传承译本中出现 {freq} 次）")
    else:
        lines.append("（本段未命中术语表）")

    if multi:
        lines.append("\n## 多义词（依语境择一，非强制；判别线索见括号）\n")
        for bo, zh, _, _ in multi:
            lines.append(f"- {bo} → {zh}")

    # 词典释义：对术语表未覆盖的多音节词查词典
    covered = {g[0] for g in glo}
    dict_hits, seen = [], set()
    syls = tools.syllables(text)
    i = 0
    while i < len(syls):
        matched = None
        for l in range(min(8, len(syls) - i), 1, -1):
            cand = "་".join(syls[i:i + l])
            if cand in seen or cand in covered:
                continue
            res = tools.lookup_dict(cand)
            if res:
                matched = (cand, res)
                break
        if matched:
            seen.add(matched[0])
            dict_hits.append(matched)
            i += len(matched[0].split("་"))
        else:
            i += 1
    lines.append("\n## 词典释义（参考·取义优先级：藏汉大辞典＞格西曲扎＞瑜伽师地论词汇表＞宝性论大疏词汇表；"
                 "同词多典义项相异时，以靠前者〔尤藏汉大辞典〕为准，余典作旁参，勿随后典飘移）\n")
    lines += render_dict_hits(dict_hits)

    # 逐字参考（兜底·治「术语表词汇有限」）：既未命中术语表、又未作为复合词命中词典的
    # 「实词单字」，拆开逐字查词典，给模型合成的原料——如 ཡོངས＝周遍、དཔྱོད＝观察 → 周遍观察，
    # 免得模型在毫无参考时把 དཔྱོད 误读作近形字 སྤྱོད(受用) 而臆造「领受」。
    covered_syls = set()
    for g in glo:
        covered_syls.update(g[0].split("་"))
    for w, _ in dict_hits:
        content = [s for s in w.split("་") if s not in PARTICLE_SYLS]
        if len(content) >= 2:             # 仅「真·多实词复合词」算已覆盖；
            covered_syls.update(content)  # 单实词+格助词(如 དཔྱོད་ཀྱིས)不算，留给逐字层取 +པ 丰义
    morph_hits, morph_seen = [], set()
    for syl in syls:
        if syl in covered_syls or syl in morph_seen or syl in PARTICLE_SYLS:
            continue
        for form in (syl + "་པ", syl):        # 先试动词/名词式(如 དཔྱོད་པ)，再试裸字
            res = tools.lookup_dict(form)
            if res:
                morph_seen.add(syl)
                sense = "；".join(res[0]["senses"])[:80]
                morph_hits.append((syl, form, sense))
                break
    if morph_hits:
        lines.append("\n## 逐字参考（复合词未成词条时，供逐字合成；非强制，仅作原料）\n")
        for syl, form, sense in morph_hits[:MORPH_MAX]:
            tag = f"〔查 {form}〕" if form != syl else ""
            lines.append(f"- {syl}{tag} → {sense}")
        if len(morph_hits) > MORPH_MAX:
            lines.append(f"（另有 {len(morph_hits) - MORPH_MAX} 个单字从略）")

    # 相似译例
    lines.append("\n## 参考译例（同一译者已定稿译本，模仿其文体）\n")
    for i, s in enumerate(segs, 1):
        for ex in tools.search_tm(s, k=2):
            if ex["score"] >= tools.TM_MIN_SCORE:
                lines.append(f"- 〔{ex['source']}｜相似度{ex['score']}〕")
                lines.append(f"  藏：{ex['bo']}")
                lines.append(f"  汉：{ex['zh']}")

    lines.append("\n---\n请按系统指令逐段翻译上方【待译原文】。")
    return "\n".join(lines)


# 内层 claude 只做「纯文本任务」：prompt 已自带全部资料。关键防护：①在中性目录运行，避免加载
# 本仓库 CLAUDE.md（其"必须走流水线"会让内层误去递归跑 pipeline、卡在权限询问而非干活）；
# ②append-system-prompt 明确其唯一任务、禁用工具与反问。
class ModelCallError(RuntimeError):
    """模型调用失败。绝不可把 stderr 当译文返回（曾 `stdout or stderr`，失败时静默产出报错文字当稿）。"""


USAGE = []            # 每次模型调用的真实用量（供体积/费用监测）
INPUT_WARN = 150_000  # 单次输入 token 超此值告警（防笔记膨胀撞上下文上限）


def _run_claude(prompt: str, model: str, guard: str) -> str:
    """调内层 claude 做纯文本任务。
    --system-prompt 取代 Claude Code 默认系统提示、--tools "" 禁用全部工具：实测「只答一字」的
    固定开销由 35,784 降至 1,527 输入 token（工具定义占绝大部分），每段两遍省约 7 万 token，
    亦根除内层模型擅调工具/跑流水线之患。--output-format json 取真实用量。
    关提示缓存（DISABLE_PROMPT_CACHING）：CLI 默认把整包按 1 小时缓存「写入」计费＝2 倍输入价，
    而资料包每段不同（待译/术语/译例/触发笔记各异）、两遍前缀也不同，实测从无复用——白付一倍。
    关掉后按 1 倍计、提示字节不变，译文不受影响。日后若批量连翻多段、改为稳定前缀走系统提示，再议开启。"""
    cmd = ["claude", "-p", "--system-prompt", guard, "--tools", "",
           "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    env = dict(os.environ, DISABLE_PROMPT_CACHING="1")
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=3000, cwd=tempfile.gettempdir(), env=env)
    except FileNotFoundError:
        raise ModelCallError("找不到 claude CLI（须安装并登录）")
    except subprocess.TimeoutExpired:
        raise ModelCallError("模型调用超时（3000 秒）")
    raw = r.stdout.strip()
    try:
        d = json.loads(raw)
    except ValueError:
        raise ModelCallError(f"模型调用失败（exit={r.returncode}）：{((r.stderr or '') + raw).strip()[:400] or '无输出'}")
    out = (d.get("result") or "").strip()
    if r.returncode != 0 or d.get("is_error") or not out:
        raise ModelCallError(f"模型调用失败（exit={r.returncode}）：{(out or r.stderr or '无输出').strip()[:400]}")
    u = d.get("usage") or {}
    tin = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    rec = {"in": tin, "cache_read": u.get("cache_read_input_tokens") or 0,
           "out": u.get("output_tokens") or 0, "usd": d.get("total_cost_usd") or 0.0}
    USAGE.append(rec)
    print(f"（模型调用：输入 {rec['in']:,} token〔缓存命中 {rec['cache_read']:,}〕·输出 {rec['out']:,}·"
          f"${rec['usd']:.3f}）", file=sys.stderr)
    if tin > INPUT_WARN:
        print(f"⚠ 单次输入 {tin:,} token 超过告警线 {INPUT_WARN:,}：笔记/资料包过大，需精简", file=sys.stderr)
    return out


def preflight(allow_missing: bool) -> list:
    """开跑前资源体检：打印摘要；缺字典/译例/术语/笔记即退出（除非 --allow-missing）。"""
    st = tools.resource_status()
    print(f"（资源：字典 {st['dicts']}·译例 {st['tm']} 条/{st['tm_files']} 文件·术语 {st['glossary']} 词头）",
          file=sys.stderr)
    if st["missing"]:
        msg = "资源缺失：" + "；".join(st["missing"])
        if not allow_missing:
            sys.exit(f"✗ {msg}\n  请先运行 python3 pipeline/rebuild.py 重建；"
                     "确需裸跑请加 --allow-missing（译文可信度下降）。")
        print(f"⚠ {msg}（--allow-missing：强行继续）", file=sys.stderr)
    return st["missing"]


def _bo_line_count(text: str) -> int:
    """统计正文对照的『藏文行』数，用于润色前后段数比对。

    只数正文：遇到「校勘/校订/译注」小节标题即停——那节里常引藏文术语（如
    རྟགས་པ/རྐྱེན），若一并计入会造成假漂移、误弃正确的润色稿。"""
    n = 0
    for ln in (text or "").splitlines():
        s = ln.lstrip("#＃ 　").strip()
        if s.startswith(("校勘", "校订", "译注", "按语")):
            break
        if any(0x0F00 <= ord(c) <= 0x0FFF for c in ln):
            n += 1
    return n


def _clean_draft(text: str) -> str:
    """剥除模型偶发的稿首噪声（英文自语/前言），使对照从首个『纯藏文行』起。
    正文藏文原文行不含拉丁字母（梵文转写只落在汉译行），据此锚定正文起点，
    杜绝『半句藏文＋英文碎语』之类噪声行虚增段数、误触兜底。"""
    lines = (text or "").splitlines()
    start = 0
    for i, ln in enumerate(lines):
        has_bo = any(0x0F00 <= ord(c) <= 0x0FFF for c in ln)
        has_latin = any("a" <= c.lower() <= "z" for c in ln)
        if has_bo and not has_latin:
            start = i
            break
    return "\n".join(lines[start:]).strip()


_FW_PUNCT = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）",
             # 补字括号统一作（）：品六校正版〔〕零次、（）为常，机器稿每段 6–44 个〔〕（学自笔记例句体例）
             "〔": "（", "〕": "）"}


def _fullwidth_cn(text: str) -> str:
    """译文一律用中文全角标点（用户裁定·恒常）。逐行处理：仅对含汉字(CJK)的行
    把半角 , ; : ! ? ( ) 转全角、补字括号〔〕统一作（）；藏文行(无汉字)不动。半角句点 . 不转，以免伤
    『6.12』『Mīmāṃsā.』等数字/梵文转写。全角引号「」『』、顿号、书名号模型已用。"""
    def is_cjk(c): return 0x4E00 <= ord(c) <= 0x9FFF or 0x3400 <= ord(c) <= 0x4DBF
    out = []
    for ln in text.splitlines():
        if any(is_cjk(c) for c in ln):
            ln = "".join(_FW_PUNCT.get(c, c) for c in ln)
        out.append(ln)
    return "\n".join(out)


def _split_tail(text: str):
    """切出正文与文末『校勘/校订/译注/按语』节（后者原样保留、不参与段级对齐）。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.lstrip("#＃ 　").strip()
        if s.startswith(("校勘", "校订", "译注", "按语")):
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()
    return text.strip(), ""


def _norm_bo(block: str) -> str:
    """取对照组内首个藏文行、提取『藏文字母骨架』作段级对齐 key。
    只留辅音/下加字/元音记号（U+0F40–U+0FBC），滤去 tsek（U+0F0B 与变体
    U+0F0C）、shad、标点、空白、数字——使同一句不因润色遍『照抄』时隐性
    规范化这些符号而匹配失败（曾致 5.28 全 17 段回退、语法适配落空）。"""
    for ln in block.splitlines():
        if any(0x0F00 <= ord(c) <= 0x0FFF for c in ln):
            return "".join(c for c in ln if 0x0F40 <= ord(c) <= 0x0FBC)
    return ""


SHRINK_MIN = 0.75     # 润色/直译汉字比下限（实测正常润色 119 段最低 0.89，中位 1.00）
LEN_RATIO_MIN = 0.5   # 汉字/藏文音节比下限（用户校正版中位 0.88、1% 分位 0.62）→ 低于即疑漏译


def _han(t: str) -> int:
    return sum(1 for c in t if 0x4E00 <= ord(c) <= 0x9FFF)


def qa_check(final: str) -> list:
    """生成后忠实性质检（只报告，不改稿）：逐段查 ①强制术语是否落地 ②汉藏长度比是否异常（疑漏译）。
    曾只校「藏文行数不变」，强制术语没落地、整句被吞都不会被发现。"""
    issues = []
    body, _ = _split_tail(final)
    for i, (_k, txt) in enumerate(_bo_pairs(body), 1):
        lines = txt.splitlines()
        bo, zh = lines[0], "\n".join(lines[1:])
        n_syl = len(tools.syllables(bo))
        if n_syl >= 15 and _han(zh) < LEN_RATIO_MIN * n_syl:
            issues.append(f"第{i}段 汉字/藏文音节 = {_han(zh) / n_syl:.2f}（基准 0.88），疑漏译")
        for t_bo, t_zh, _f, multi in tools.scan_glossary(bo):
            if multi:
                continue
            core = tools._CORE_CUT.split(t_zh, 1)[0]
            alts = [a.strip(" 「」『』") for a in re.split(r"[／/、，,]", core) if a.strip()]
            if alts and not any(a in zh for a in alts):
                issues.append(f"第{i}段 强制术语未落地：{t_bo} → {core}")
    return issues


def _bo_pairs(body: str):
    """逐行切对照组（不依赖空行）：每个『纯藏文行』起一组，其后非藏文行（汉译）归入该组。
    返回 [(藏文骨架key, 组原文)]。润色稿常漏段间空行而粘成一块，按空行切会整篇对不上。"""
    def is_bo_line(l):
        return any(0x0F00 <= ord(c) <= 0x0FFF for c in l) and \
            not any(0x4E00 <= ord(c) <= 0x9FFF for c in l)
    pairs, cur = [], None
    for ln in body.splitlines():
        if is_bo_line(ln):
            if cur:
                pairs.append(cur)
            cur = [_norm_bo(ln), [ln]]
        elif cur is not None:
            cur[1].append(ln)
    if cur:
        pairs.append(cur)
    return [(k, "\n".join(lines).strip()) for k, lines in pairs]


def _merge_polished(draft: str, polished: str):
    """段级对齐兜底：以直译稿段序为准，逐段取润色稿中对应段之汉译，对不上的个别段回退直译。
    三级匹配（曾因只认『藏文骨架全等＋空行切段』，6.10 润色 13 段全数回退）：
      ① 骨架全等；② 骨架近似（≥0.85，偏向保持顺序）；③ 两稿段数相同时按位置（骨架≥0.5）。
    润色段若无汉译则视为对不上；汉字数缩到直译 SHRINK_MIN 以下视为疑吞句，亦回退。
    返回 (合并稿, 回退段数, 说明列表)。"""
    from difflib import SequenceMatcher
    d_body, tail = _split_tail(draft)
    p_body, _ = _split_tail(polished)
    d_pairs, p_pairs = _bo_pairs(d_body), _bo_pairs(p_body)
    has_zh = lambda t: any(0x4E00 <= ord(c) <= 0x9FFF for c in t)
    p_pairs = [(k, t) for k, t in p_pairs if has_zh(t)]
    exact = {}
    for j, (k, _) in enumerate(p_pairs):
        exact.setdefault(k, j)
    same_len = len(p_pairs) == len(d_pairs)
    used, merged, fallback, pos, notes = set(), [], 0, 0, []
    for i, (k, txt) in enumerate(d_pairs):
        j = exact.get(k)
        if j is None or j in used:
            j, best = None, 0.0
            for jj, (pk, _) in enumerate(p_pairs):
                if jj in used:
                    continue
                sm = SequenceMatcher(None, k, pk)
                if sm.real_quick_ratio() < 0.85:
                    continue
                r = sm.ratio() + (0.02 if jj >= pos else 0.0)
                if r > best:
                    best, j = r, jj
            if best < 0.85:
                j = None
                if same_len and i not in used and \
                        SequenceMatcher(None, k, p_pairs[i][0]).ratio() >= 0.5:
                    j = i
        if j is not None:
            used.add(j)
            pos = j + 1
            # 藏文行一律取直译稿原文（润色只许改汉译），汉译取润色稿
            d_bo = txt.splitlines()[0]
            p_zh = "\n".join(p_pairs[j][1].splitlines()[1:]).strip()
            d_n, p_n = _han("\n".join(txt.splitlines()[1:])), _han(p_zh)
            if d_n >= 20 and p_n < SHRINK_MIN * d_n:      # 润色明显缩水＝疑吞句→回退该段直译
                merged.append(txt)
                fallback += 1
                notes.append(f"第{i + 1}段 润色稿汉字仅直译稿的 {p_n / d_n:.0%}（疑吞句），回退直译")
                continue
            merged.append(d_bo + "\n" + p_zh)
        else:
            merged.append(txt)
            fallback += 1
            notes.append(f"第{i + 1}段 润色稿中对不上，回退直译")
    out = "\n\n".join(merged)
    if tail:
        out += "\n\n" + tail
    return out, fallback, notes


def build_polish_packet(draft: str, src_text: str) -> str:
    """第二遍润色资料包：润色规范 + 文风笔记 + 术语约束（守住不改）+ 直译稿。"""
    lines = [POLISH_FILE.read_text(encoding="utf-8")]
    # 文风笔记按当前项目取（约定为笔记层最后一件 …/文风.md）
    wind = next((n for n in tools.project_notes() if n.name == "文风.md"), None)
    if wind and wind.exists():
        lines.append("\n---\n" + gate_sections(wind.read_text(encoding="utf-8"), src_text, wind.name)[0])
    # 术语约束：让润色明确哪些译名必须保持不动
    glo = tools.scan_glossary(src_text)
    fixed = [g for g in glo if not g[3]]
    if fixed:
        lines.append("\n## 术语约束（润色时一律保持不动）\n")
        for bo, zh, _, _ in fixed:
            lines.append(f"- {bo} → **{zh}**")
    lines.append("\n---\n## 待润色·直译稿（藏文行照抄不动，仅重写汉译行）\n")
    lines.append(draft)
    lines.append("\n---\n请按【译文润色规范】只改行文、不动义理，输出润色后的藏汉逐段对照全文。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--file", type=Path)
    ap.add_argument("--packet", action="store_true", help="只输出资料包，不调用模型")
    ap.add_argument("--polish", action=argparse.BooleanOptionalAction, default=True,
                    help="翻译后再跑一遍『文风润色』（默认开；--no-polish 关）。两阶段：准确直译→定稿体润色")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--model", default="")
    ap.add_argument("--allow-missing", action="store_true",
                    help="资源（字典/译例/术语/笔记）缺失时仍强行运行（默认缺失即报错退出）")
    ap.add_argument("--project", default="gzhanstong",
                    help="翻译项目：gzhanstong(胜乘中观·默认) / kalacakra(时轮根本续)。"
                         "决定注入哪套笔记/译例/术语覆盖层；两本词典与共享术语库始终共用")
    args = ap.parse_args()

    tools.set_project(args.project)   # 切项目：选定 notes/tm/术语覆盖层（默认不改变原行为）

    text = args.text or (args.file.read_text(encoding="utf-8") if args.file else None)
    if not text:
        ap.error("需要 --text 或 --file")

    missing = preflight(args.allow_missing)
    packet = build_packet(text, missing)
    print("（笔记注入：" + "；".join(NOTE_REPORT) + "）", file=sys.stderr)
    if args.packet:
        print(packet)
        return

    guard1 = ("你是藏译汉『译经引擎』。下方用户消息已含全部所需资料"
              "（系统指令·法义/句法/文风笔记·术语约束·词典释义·参考译例·待译原文）。"
              "唯一任务：按系统指令逐段输出藏汉逐段对照译文。"
              "第一行必须就是第一段藏文原文，严禁任何前言、自语、英文或说明；"
              "严禁调用任何工具、运行脚本或本仓库流水线，严禁询问权限或反问，直接输出译文。")
    try:
        draft = _clean_draft(_run_claude(packet, args.model, guard1))   # 第一遍：准确直译（清洗稿首噪声）
    except ModelCallError as e:
        sys.exit(f"✗ 直译遍失败，未产出译文：{e}")
    if not draft:
        sys.exit("✗ 直译遍输出清洗后为空（无藏文对照行），未产出译文")
    out = draft

    if args.polish:
        # 第二遍『语法适配』：汉语语序/成分位置/虚词/断句的通顺化 + 文风定稿，不动义理/术语/对照。
        guard2 = ("你是藏译汉定稿润色师。下方已含直译稿·文风笔记·术语约束。"
                  "唯一任务：只改汉译行文、不动义理/术语/格式（藏文行照抄），输出润色后的对照全文。"
                  "严禁调用任何工具或反问，直接输出。")
        try:
            polished = _clean_draft(_run_claude(build_polish_packet(draft, text), args.model, guard2))
        except ModelCallError as e:
            polished = ""
            print(f"⚠ 润色遍失败，交付直译稿：{e}", file=sys.stderr)
        # 段级对齐兜底：段数恒守恒（=直译段数），通顺化尽量采纳；润色对不上的个别段回退该段直译。
        if not polished:
            print("（语法适配遍无输出，保留直译稿）", file=sys.stderr)
        else:
            out, fb, merge_notes = _merge_polished(draft, polished)
            tag = "全段采纳" if fb == 0 else f"{fb} 段回退直译"
            print(f"（语法适配遍：{_bo_line_count(draft)} 段·{tag}）", file=sys.stderr)
            for n in merge_notes:
                print(f"  · {n}", file=sys.stderr)
            if fb and args.out:                       # 存润色原稿，供诊断对不上的原因
                raw_p = args.out.with_name(args.out.stem + "_润色原稿" + args.out.suffix)
                raw_p.write_text(polished + "\n", encoding="utf-8")
                print(f"（润色原稿另存 {raw_p}，供诊断）", file=sys.stderr)

    out = _fullwidth_cn(out)          # 译文定稿一律中文全角标点（用户裁定·恒常）
    draft = _fullwidth_cn(draft)
    if USAGE:
        tot_in = sum(u["in"] for u in USAGE); tot_out = sum(u["out"] for u in USAGE)
        print(f"（本次合计：{len(USAGE)} 次调用·输入 {tot_in:,} token·输出 {tot_out:,}·"
              f"${sum(u['usd'] for u in USAGE):.3f}）", file=sys.stderr)
    issues = qa_check(out)
    if issues:
        print(f"⚠ 质检：{len(issues)} 处待核（强制术语未落地/疑漏译）", file=sys.stderr)
    else:
        print("（质检：强制术语全部落地，无疑漏译段）", file=sys.stderr)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
        print(f"译文已写入 {args.out}")
        qa_p = args.out.with_name(args.out.stem + "_质检" + args.out.suffix)
        qa_p.write_text("# 质检报告（自动·只报告不改稿）\n\n" +
                        ("\n".join(f"- {x}" for x in issues) if issues else "无待核项。") +
                        "\n\n## 笔记注入（专项规则按触发词注入；如疑某条该用而未注入，查此）\n\n" +
                        "\n".join(f"- {r}" for r in NOTE_REPORT) + "\n",
                        encoding="utf-8")
        print(f"（质检报告 {qa_p}）")
        # 润色时把纯直译稿一并另存，供日后「机器直译↔用户校正版」diff 提炼文风规律。
        if args.polish and out is not draft:
            draft_path = args.out.with_name(args.out.stem + "_直译" + args.out.suffix)
            draft_path.write_text(draft + "\n", encoding="utf-8")
            print(f"（纯直译稿另存 {draft_path}）")
    else:
        print(out)


if __name__ == "__main__":
    main()
