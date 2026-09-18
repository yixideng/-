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
    ROOT / "data/processed/tm_gzhanstong_49.jsonl",        # 同上（品四 理证收尾·5根颂+疏·染净因果皆依阿赖耶[造业习气·初禅同类因·母子慈心生梵天喻·世出世间道种子成熟]·破外道[阿赖耶≠数论主/自在/大梵,仅方向相似依阿赖耶假立·唯心·引楞伽经]·破一切种顿现[月称入中论前宗·一切种=同类具足·瓶种喻·缘次第现]）
    ROOT / "data/processed/tm_gzhanstong_410.jsonl",       # 同上（品四 习气新旧安置·新旧俱滋养·因果俱时[能依所依因果]破法称异时诘难·分两种因果·成立染污意理证三式[有漏善/二定别/我执相续]）
    ROOT / "data/processed/tm_gzhanstong_411.jsonl",       # 同上（品四 染污意教证[杂阿含]·无著不共无明[声闻误置意识/本论置末那]·八识成立·习气异名[习气/能/粗重]·六种子·四习气[名言/身见/业/二取]·等流异熟）
    ROOT / "data/processed/tm_gzhanstong_412.jsonl",       # 同上（品四 阿赖耶异名门·轮回粗细二转依[性相/体性]·天授祠授遍喻·六义[因果作业相应所缘趣入]·四缘七识增上缘·破「前刹那识必为等无间缘」青花刹那相续）
    ROOT / "data/processed/tm_gzhanstong_413.jsonl",       # 同上（品四 非真实遍计[辨中边论·寻伺判摄]·识—心所分工·七识近受用/遍受用·受想行三心所·轮回生灭[大乘庄严经论·自之界]·无明独标·离二实一识现二相）
    ROOT / "data/processed/tm_gzhanstong_414.jsonl",       # 同上（品四轮回还灭·止观四所缘[法内外二·据大乘庄严经论]·法所缘=经乃法身等流印模印入自相续·同一境染净由如理/非如理作意分[美女喻]·止观双运→心善解脱(离等至障)/慧善解脱(离烦恼障)=俱分解脱·道由二显生还破二显[蝎/木蠹喻]·善解脱[非极解脱]对字；含汉传暗引:大乘庄严经论世亲释/集论止观定义/解深密经疏心慧善解脱）
    ROOT / "data/processed/tm_gzhanstong_52.jsonl",        # 品五（名之六分类[事名/关联名/总摄名/别名/共许名/不共许名]·分别分类[有相无相/染污非染污/趣入境寻求者别别]·五法多重判摄:有无[分别正智实有·名假立有·因相多假立有但能取分实有·如如胜义有]·一异[名因相非一非异]·三性[因相多+名=遍计,分别正智=依他起,如如=圆成实]·四谛[因相全分·名唯苦谛·灭谛=如如·十六行相皆正智所缘]·二谛[名因相所取世俗/分别世俗谛/正智异门胜义/如如真实胜义]·「法」字义=五事[dngos po=存在物义,非实法]）
    ROOT / "data/processed/tm_gzhanstong_51.jsonl",        # 品五（五法体性·相名分别真如正智[据楞伽/密严]·4根颂+疏·因相=境共相[非原由]/名=声共相现心/分别=心心所/真如=离言唯圣者根本定行境/正智=道智两分等引出世·后得有二显非出世·具引出世非出世相；因相分类:自性因相[现证所生/共许所生·名物非一非属唯共许假立]vs色影因相[邪宗遍计我执];因相再分通达明→有相/未通达不明→无相;遍计起vs俱生起·五见分判[邪见见取戒禁取纯分别起,贪嗔兼二分]·量论执取方式所取长链合译）
    ROOT / "data/processed/tm_gzhanstong_415.jsonl",       # 同上（品四义摄结颂[品竟]·3根颂+疏·还灭总义[分别→业苦→习气]·大乘还灭[善法分别→见道无分别智摧二显种子→十地断微细苦集→无住涅槃]·小乘还灭[削弱种子·量减非根断·仅于道作差别]·出离三层[厌此生苦<厌恶趣苦<厌一切轮回=小乘共出离<从唯世俗因缘显现轮回决定出离=大乘究竟出离]·八识教开二无我门[刹那无常不实→人无我·互为因果缘起显现→法无我]）
    ROOT / "data/processed/tm_gzhanstong_55.jsonl",        # 品五（依他/圆成分类·4根颂+疏·依他二分[种子依他=杂染/非染净体性依他=清净觉知未为习气所转·体性无别·澄水现虚空白喻]+净不净世间依他[习气力现三界心心所谛实/圣者后得如幻]·楞伽六依他[眼识+境色+眷属心所+此三所依止之染污意阿赖耶=一门·配六识聚分六分]·圆成无著四种[自性/无垢/道/所缘·摄论]·弥勒二种[无变异/无颠倒·辨中边]·后二道所缘圆成随顺无颠倒具依他性相却成断依他对治[以迷乱遣迷乱]·skyes bu=补特伽罗/ldog cha=遮返分）
    ROOT / "data/processed/tm_gzhanstong_56.jsonl",        # 品五（三性一异抉择·摄二·破净依他独存·圆成二种·2根颂+疏·义理高峰·三性非一非异[遍计snang cha显现分/依他snang ba显现·不相离非异·有离二显净识依他故非一;火薪喻;麻油蔗糖虚空遍物喻]·主要义遍计+依他对圆成作有法↔法性·摄二两轴[胜义真妄归摄:依他摄入遍计唯余圆成 vs 存在施设:遍计依托依他·勿混]·此处法性=世俗法性·净依他≠真圆成[唯离二取戏之内能取识nang dzin·真圆成=法性界智双运dbyings ye zung jug]·破唯识假象派rnam rdzun pa[安慧系·净依他=真圆成解脱位存·假名yongs grub dngos·水晶投石喻·断遍计则依他尽]·圆成二种[自性=灭谛胜义/清净=道谛名清净体属依他]·安慧=假相派）
    ROOT / "data/processed/tm_gzhanstong_54.jsonl",        # 品五（三性圆成后二相·三性摄·三无自性·龙树世亲教证·遍计分类·5根颂+疏·圆成第二相[不寂寂平等:寂由障分非圆成自身·恒具二障寂性相]第三相[无分别]·辨中边三性摄[遍计=似现外事错乱显现/依他=虚妄遍计三界心心所/圆成=二取无为差别之真如]·三无自性约二谛[遍计二谛恒无=相无性/依他世俗有胜义无=生无性/圆成体性有二取无=胜义无性;玄奘译三十颂三无性偈暗引]·龙树稻杆经释[因相=遍计·五门识+阿赖耶意=依他·非所遍计=圆成]与世亲三十颂[圆成两重疏解:权约世俗/遍计尽依他亦尽唯余圆成]会通弥勒·遍计三分[性相断灭人我/异名能所二取/观待东西]+所依因相vs能作分别[无量由能作出]+自性遍计瓶体/差别遍计瓶上大小好恶·rgyu mtshan此段=因相[校正版]）
    ROOT / "data/processed/tm_gzhanstong_53.jsonl",        # 品五（三性略示广说体性·5根颂+疏·三性于同一所相事上安置[遍计=意言假立分/依他=自因缘生唯了别识(「自之」=了别识·「生」=从相顺相宜缘生,非俱生)/圆成=胜义实相真如]·不作无穷内分类[圣般若十万颂遍计色分别色法性色只是安置三性]·依他起=遍计所执之所依[ཀུན་ཏུ་རྟོག་པ=ཀུན་བརྟགས=遍计,不区分;习气二分:显现是识实体→依他,现为独立外境之方式→遍计迷乱显现;不为习气所控则住自立·去「力」字]·名义非同位[火/阿耆尼喻·否则烧口应成过]·量论七执取[执名为事等·摄大乘论]·依他六相[处事身3所取+意能取分别3能取=三界心心所虚妄遍计]·圆成三相[有无平等/不寂静寂静平等/无分别]·有无平等=二取无与自体有二者平等[非一对二,圆成法性真如即此平等本身]）
    ROOT / "data/processed/tm_gzhanstong_57.jsonl",        # 品五（引申义·弥勒十种散乱分别·1根颂+疏·《大乘庄严经论》「无体体增减,一异自别相,如名如义」十分别·他空以三性判摄:无=依他世俗无+连带遍计世俗无/有=依他世俗有+连带依他胜义无[正显他空]/增益损减/执一[警:直指偶然显现rang 'ga' ma为法身空性堕此]执多异/执自性瓶khyad gzhi所别事/差别生住灭/如名起义/如义起名·皆散乱分别rnam g.yeng=摄论散动·能周遍安立kun tu 'dogs byed·增益假立分=遍计所执之主体kun btags dngos[dngos=主体/正体对假名]·rnam rig tsam=唯识不拆译·zhor byung=连带·般若十对治参庄严经论世亲释[校订本录全文]）
    ROOT / "data/processed/tm_gzhanstong_58.jsonl",        # 品五（根本分别·十种[妄想]分别·十一识现·唯识无外境·世俗真实·2根颂+疏·11组）前半:《摄论》十种分别(list A)他空疏[假立分皆遍计]:根本=阿赖耶/相mtshan ma所取+显现相mtshan snang根识能取+变相mtshan 'gyur受相变→显现相变snang 'gyur/不如理+如理[假立分仍属遍计]→他引gzhan bstan/执著mngon zhen=六十二恶见见稠林lta ba 'thib po/第十=散动分别=5.7弥勒十分别(list B·总别嵌套非等同·先前误「十种分别=十散动」已改·列九+散动=十);后半:依他起相十一识现rnam rig[身/具身五根/能食za po意根/所受用六境/能受用六转识→摄十八界+时数处言说(名言习气)+显现我他(我见习气)+善趣恶趣死生(有支习气)]·唯识无外境=中观自宗清净世俗yang dag kun rdzob·唯识胜义无而世俗真实[rnam rig tsam住世俗谛]·术语:rnam rig(vijñapti)=识现/了别·rnam par shes pa(vijñāna)=识·rnam rig tsam=唯识;含汉传暗引:大乘庄严经论世亲释十分别对治/摄论十散动/摄论十种分别list A/摄论依他起相十一识）
    ROOT / "data/processed/tm_gzhanstong_59.jsonl",        # 品五（三性有无水月喻·三性遍所相事/烦恼/道/果法身·三空性·6根颂+2教证+疏·17组）三性有无:澄水现日月影·影↔水体性无别·世俗「水有影无」·遍计=影(无byed nus能作业体)/唯识rnam shes tsam=水(正世俗体性有)·了义胜义二俱无·余=离二取智恒有谛实;破净识独存:依他遮遍计所余唯清净识=假名圆成·执为究竟胜义则不出唯识宗sems tsam grub mtha'·真圆成=离二取智慧法性;能遍所遍:法性遍依他·姑说遍遍计究实不遍(遍计二谛恒无·虚空遍水不遍影);三性遍瓶/贪嗔(ro mnyam一味:明觉分体异不相遍圆成无别)/道/果法身·诫thob pa thug med得无穷套叠;三空性[弥勒庄严经论]:遍计=无有空性med pa'i stong nyid/依他=实有空性yod pa'i stong nyid[世俗层]/圆成=自性空性rang bzhin stong nyid[空遍计依他二他];末段无自性宗:入中论VI.23二体性·空性=胜义谛·lugs 'di=无自性宗(非他空·全段内在该宗)·「一切法唯空」chos thams cad stong nyid于此宗最契合;含教证:入中论VI.23/弥勒三空性颂/阿阇梨颂;句法:nam mkha'i=名词化因由句属格主语phyir承后省略）
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
