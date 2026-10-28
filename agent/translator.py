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
    for block in blocks:
        parts = _shad_clauses(block)
        if len(parts) <= max_shad:            # 常态：自然段整体成一组
            if parts:
                segs.append(" ".join(parts))
            continue
        # 超长段兜底：先按句末终结词切成整句，再贪心地把整句打包成 ≤max_shad 的组。
        # 这样断点总落在真实句界（如 …གྲུབ་བོ།│རང་རིག་…），不会因「凑够 max_shad 才断」
        # 而把两段论证挤在一起或越过句界；单句本身超长则整句保留（不腰斩）。
        sentences, cur = [], []
        for p in parts:
            cur.append(p)
            if _sentence_end(p):
                sentences.append(cur)
                cur = []
        if cur:                               # 末尾无终结词的残句自成一句
            sentences.append(cur)
        group = []
        for sent in sentences:
            if group and len(group) + len(sent) > max_shad:
                segs.append(" ".join(group))
                group = []
            group += sent
        if group:
            segs.append(" ".join(group))
    return segs


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


def build_packet(text: str) -> str:
    segs = split_segments(text)
    lines = []
    lines.append(PROMPT_FILE.read_text(encoding="utf-8"))
    # 笔记层：法义纲要 + 句法通则（恒常注入，先于原文，供全篇遵循）——按当前项目取
    for nf in tools.project_notes():
        if nf.exists():
            body = nf.read_text(encoding="utf-8")
            if nf.name == "法义.md":           # 通则全量；逐段纪要按需节选（防提示膨胀稀释规则）
                body = select_fayi(body, text)
            lines.append("\n---\n" + body)
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
    lines.append("\n## 词典释义（参考·取义优先级：藏汉大辞典＞格西曲扎；"
                 "同词多典义项相异时，以靠前者〔尤藏汉大辞典〕为准，余典作旁参，勿随后典飘移）\n")
    for word, entries in dict_hits[:25]:
        for e in entries[:2]:
            sense = "；".join(e["senses"])[:150]
            lines.append(f"- {word}〔{e['source']}〕{sense}")

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
        for syl, form, sense in morph_hits[:20]:
            tag = f"〔查 {form}〕" if form != syl else ""
            lines.append(f"- {syl}{tag} → {sense}")

    # 相似译例
    lines.append("\n## 参考译例（同一译者已定稿译本，模仿其文体）\n")
    for i, s in enumerate(segs, 1):
        for ex in tools.search_tm(s, k=2):
            if ex["score"] >= 0.15:
                lines.append(f"- 〔{ex['source']}｜相似度{ex['score']}〕")
                lines.append(f"  藏：{ex['bo']}")
                lines.append(f"  汉：{ex['zh']}")

    lines.append("\n---\n请按系统指令逐段翻译上方【待译原文】。")
    return "\n".join(lines)


# 内层 claude 只做「纯文本任务」：prompt 已自带全部资料。关键防护：①在中性目录运行，避免加载
# 本仓库 CLAUDE.md（其"必须走流水线"会让内层误去递归跑 pipeline、卡在权限询问而非干活）；
# ②append-system-prompt 明确其唯一任务、禁用工具与反问。
def _run_claude(prompt: str, model: str, guard: str) -> str:
    cmd = ["claude", "-p", "--append-system-prompt", guard]
    if model:
        cmd += ["--model", model]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=3000, cwd=tempfile.gettempdir())
    return r.stdout.strip() or r.stderr.strip()


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


_FW_PUNCT = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）"}


def _fullwidth_cn(text: str) -> str:
    """译文一律用中文全角标点（用户裁定·恒常）。逐行处理：仅对含汉字(CJK)的行
    把半角 , ; : ! ? ( ) 转全角；藏文行(无汉字)不动。半角句点 . 不转，以免伤
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
    润色段若无汉译则视为对不上。返回 (合并稿, 回退段数)。"""
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
    used, merged, fallback, pos = set(), [], 0, 0
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
            merged.append(d_bo + "\n" + p_zh)
        else:
            merged.append(txt)
            fallback += 1
    out = "\n\n".join(merged)
    if tail:
        out += "\n\n" + tail
    return out, fallback


def build_polish_packet(draft: str, src_text: str) -> str:
    """第二遍润色资料包：润色规范 + 文风笔记 + 术语约束（守住不改）+ 直译稿。"""
    lines = [POLISH_FILE.read_text(encoding="utf-8")]
    # 文风笔记按当前项目取（约定为笔记层最后一件 …/文风.md）
    wind = next((n for n in tools.project_notes() if n.name == "文风.md"), None)
    if wind and wind.exists():
        lines.append("\n---\n" + wind.read_text(encoding="utf-8"))
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
    ap.add_argument("--project", default="gzhanstong",
                    help="翻译项目：gzhanstong(胜乘中观·默认) / kalacakra(时轮根本续)。"
                         "决定注入哪套笔记/译例/术语覆盖层；两本词典与共享术语库始终共用")
    args = ap.parse_args()

    tools.set_project(args.project)   # 切项目：选定 notes/tm/术语覆盖层（默认不改变原行为）

    text = args.text or (args.file.read_text(encoding="utf-8") if args.file else None)
    if not text:
        ap.error("需要 --text 或 --file")

    packet = build_packet(text)
    if args.packet:
        print(packet)
        return

    guard1 = ("你是藏译汉『译经引擎』。下方用户消息已含全部所需资料"
              "（系统指令·法义/句法/文风笔记·术语约束·词典释义·参考译例·待译原文）。"
              "唯一任务：按系统指令逐段输出藏汉逐段对照译文。"
              "第一行必须就是第一段藏文原文，严禁任何前言、自语、英文或说明；"
              "严禁调用任何工具、运行脚本或本仓库流水线，严禁询问权限或反问，直接输出译文。")
    draft = _clean_draft(_run_claude(packet, args.model, guard1))   # 第一遍：准确直译（清洗稿首噪声）
    out = draft

    if args.polish:
        # 第二遍『语法适配』：汉语语序/成分位置/虚词/断句的通顺化 + 文风定稿，不动义理/术语/对照。
        guard2 = ("你是藏译汉定稿润色师。下方已含直译稿·文风笔记·术语约束。"
                  "唯一任务：只改汉译行文、不动义理/术语/格式（藏文行照抄），输出润色后的对照全文。"
                  "严禁调用任何工具或反问，直接输出。")
        polished = _clean_draft(_run_claude(build_polish_packet(draft, text), args.model, guard2))
        # 段级对齐兜底：段数恒守恒（=直译段数），通顺化尽量采纳；润色对不上的个别段回退该段直译。
        if not polished:
            print("（语法适配遍无输出，保留直译稿）", file=sys.stderr)
        else:
            out, fb = _merge_polished(draft, polished)
            tag = "全段采纳" if fb == 0 else f"{fb} 段对不上·已回退该段直译"
            print(f"（语法适配遍：{_bo_line_count(draft)} 段·{tag}）", file=sys.stderr)
            if fb and args.out:                       # 存润色原稿，供诊断对不上的原因
                raw_p = args.out.with_name(args.out.stem + "_润色原稿" + args.out.suffix)
                raw_p.write_text(polished + "\n", encoding="utf-8")
                print(f"（润色原稿另存 {raw_p}，供诊断）", file=sys.stderr)

    out = _fullwidth_cn(out)          # 译文定稿一律中文全角标点（用户裁定·恒常）
    draft = _fullwidth_cn(draft)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
        print(f"译文已写入 {args.out}")
        # 润色时把纯直译稿一并另存，供日后「机器直译↔用户校正版」diff 提炼文风规律。
        if args.polish and out is not draft:
            draft_path = args.out.with_name(args.out.stem + "_直译" + args.out.suffix)
            draft_path.write_text(draft + "\n", encoding="utf-8")
            print(f"（纯直译稿另存 {draft_path}）")
    else:
        print(out)


if __name__ == "__main__":
    main()
