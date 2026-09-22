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
    ROOT / "data/processed/tm_gzhanstong_510.jsonl",       # 品五（三空性[般若五百颂=惟净译开觉自性般若·色中空三摩地·无实空性/实有空性/自性空性=無性空/性空/本性空]·经说有无密意[无著世亲:凡夫所现实义中无→说无·迷乱心前如是现→说有]·三无自性约三时[未来未生/过去已灭/现在刹那不住]·阿阇梨三无自性颂·由三性引申缘起二分[所生能生=依他/所安立能安立=遍计·非决定周遍;分位vs真实;外器种田水肥→芽穗·内情业习气→身语意·内识四缘生根识;观待种子识↔芽识因果执=假立有显现分·不观待须弥↔雪山大小相待]·圆成非世俗缘起是胜义缘起/瑜伽士心前新起;含汉传:开觉自性般若/摄论有无颂/摄论释世亲真谛;句法:色法中空性之色法中三摩地[双ལ同位属格·ཏིང་ངེ་འཛིན作宾语无ལ]·X དང་ཞེས་པ引用收尾非「和」·nam mkha'i因由句属格主语）
    ROOT / "data/processed/tm_gzhanstong_511.jsonl",       # 品五（真实缘起=具一切习气阿赖耶识·缘起词义二训[①会集ཚོགས་པ+utpāda生+saṃ正生→众缘会际生众果·通两轴;②pratītya先(prati+√i依/趣)+相属saṃbandha→前后相属而生·唯通能生所生]·缘起三分=摄论二缘起+受用[分别自性缘起=等流自类·名言习气·种现同类体性相顺·唯大乘菩萨佛知/分别爱非爱缘起=十二支·异熟异性·有支习气·声闻独觉/受用=六识·声闻];rnam par 'byed pa=分别(分出)本义vibhāga[摄论定译分别·辨中边作辨·非辨别非vikalpa]此处引申训增长广大;ngo bo nyid=自性偏各别自体义[非圆成胜义];don mthun=体性相顺自类等流[非同质合一];de gnyis=显现与种子互为因果故名自性;含汉传:摄论二缘起+愚二缘起·pratītya词源注）
    ROOT / "data/processed/tm_gzhanstong_514.jsonl",       # 品五（十二支别释续[承5.13b·12段含2摄颂]:①辩破一业二异熟[无明行既生所引四支又生老死→一业二异熟过·俱舍有壳果/药/花喻=一业一异熟]②三世二次因果=引生混杂[无明行→识…受第一重/爱取→有生老死第二重]·遮三际愚[前际无明行/中际识…有八/后际生老死·俱舍前后二际各二中八颂]③一生圆满[次第不乱·破乱序说·顺现法受女身转喻]④刹那缘起[一业时量内十二支并俱非时序·须成缘与具缘·杀生喻]⑤相属缘起两说[说一每刹那满十二支自类相续近取因+助缘/说二一支一刹那顺次相生·皆可通];辩破乱序应成破[体性不一则违经三句(无明缘行/取缘有/行缘识)vs对方(无明生爱/取生行/行生有)·体性一则支数不全];校勘:ལེན་པའི་རྐྱེན་གྱིས་སྲེད་པ→སྲིད་པ「取缘有」(用户标注·有支条以取为缘定义+三句平行结构);འཕེན་འགྲིབ=འཕེན་འགྲུབ引生;术语:有壳果/顺现法受མཐོང་ཆོས་མྱོང་འགྱུར/三际/供养བསྙེན་བཀུར/助缘=俱有缘/缘与具缘/ཐ་དད་པ他动;句法:སྲེད↔སྲིད形近讹字警戒·作格判主宾(ཐ་དད་པ带ས=施动/零标记=受动·杀一有情)·X-པའི་བྱ་བ+དེ回指;义理:十二支四门时间尺度全景[分位生级/刹那一业并俱/相属刹那相续/相续长时流]·女身转喻业报同类相酬全染污业）
    ROOT / "data/processed/tm_gzhanstong_513b.jsonl",      # 品五（分位缘起长行·辩破三生混杂说[承5.13a末二摄颂;4段长行]:①分位二算法[二生说自宗=欲界二生圆满一次十二缘起·无明行能引/识…受五所引/爱取有能生/生老死所生·引成四支一次因果唯二生圆满;三生说=三生ཚར་རེ圆满一次·与ཚར་གཅིག同「一次」唯二生三生之别]②说十二支必要=植种养种[能引二+能生二令知植种·所引五+所成三令知养种·有支归属数目差异系原文内在两分判]③印藏混杂说=把三生二重因果(依序生起缘起)与引成四支二生圆满相混[第一生无明行能引/中间生识等五所引/中间生爱取乃至三生结生前有支能生/三生生老死所生]④辩破应成破=二说相混则非成二者(两不像)不应理·名色等四成非所引支(乃所生支因已现行非唯种子)·敌辩虽现起亦无妨为所引支·作者破性相不具而立名则太过;义理:破斥非破「识至受=所引支」(共许)乃破「摊所引支于中间生现行·毁种子位性相又保其名」之自语相违·所引支=种子位由推定升为原文明用(②非唯种子乃已现行故);术语:能生支/所生支[用户定谳覆盖5.13a能成/所成]·依序生起缘起·植种养种·印藏二地;句法:应成破立敌句式甲读定谳·ཚར་རེ=圆满一次非分配·原文数目两分判照录）
    ROOT / "data/processed/tm_gzhanstong_513a.jsonl",      # 品五（缘起八分后四分:③依食养命[四食段/触/思/识·后三食前前生后后·俱舍四食颂]④可欲不可欲趣[善业→可欲善趣/不善→不可欲恶趣=杂染缘起]⑦清净[五道三学资粮加行见修·体性=现前无学道]⑧威力[六神通·圣菩萨=威力正性相/资加行五=随顺/外道世间道=俱非·庄严经论六神通颂]·八分总摄[皆相属缘起就能生所生·实法关联为主·六染二净四内二外]·十二支别释科判[四门刹那/相属/分位/相续·分位相续合=三门]·分位缘起二生↔三生摄颂[二生说=引成四支因果一次ཚར་གཅིག/三生说=因果二次ཚར་གཉིས引成无别混杂被破·二说不相杂·为令知种子播植长养·为遮三愚];术语:ཟས་ཀྱི་འཚོ་བ依食养命·འདོད་པ/མི་འདོད་པ可欲/不可欲(覆盖5.12往愿)·ཐར་བའི་གོ་འཕང解脱果位(非佛位)·ཐོགས་མེད་བརྟན་པ无碍坚固(非无著)·རྗེས་མཐུན随顺·ཚར་གཉིས二重因果(非二遍)·能引/所引/能成/所成支;含汉传暗引:大乘庄严经论波罗颇译六神通长行;句法:ཚར数量词厘定·所引支=种子位系推定非明文·科判摄颂体例·教证长行不入平行文;止于三生混杂摄颂,长行辩破段待5.13b）
    ROOT / "data/processed/tm_gzhanstong_512.jsonl",       # 品五（分别爱非爱缘起字义[补5.11 gap:分别=增长广大·爱/非爱=悦意/不悦意·染净二门=杂染门(有漏善→善趣爱/不善→恶趣非爱)+清净门(善恶业→六趣非爱/无漏善→解脱爱)·皆就爱非爱果相立名]·受用缘起=识生缘起=六识聚生灭方式[受用者=受/近伺察所受用=触·声闻主修]·四缘生眼识[所缘缘悦意境色/增上缘眼根/因缘眼识初刹那/等无间缘欲趋境作意]·触受思染心王·嗔痴门类推·细微无常[前刹那识=次刹那识近取因·前刹那心所=次刹那识俱有缘]·声闻修人无我戒断·阿罗汉转依[六识各各现量证无我转无漏·染污意阿赖耶不转无漏但性相坏不起作业·显现为我余习不引后有不积新业·喻颂咒班智达空诵/城王失半国·非灭阿赖耶乃坏染用]·缘起八分[①识生=受用②死迁受生=杂染缘起=分别爱非爱十二支③外缘起种芽茎节穗果果复为种④器世间成坏三千大千南赡部洲寿量无量→十岁→八万岁皆有情共业所现];术语:sdug pa/mi sdug pa=爱/非爱(覆盖术语约束可爱)·mtshungs ldan=相应俱行·nyer spyod can=受用缘起·四缘定名dmigs pa'i/bdag po'i/rgyu/de ma thag rkyen· nyer len gyi rgyu近取因/lhan cig byed pa'i rkyen俱有缘·sdom pa戒断·mngon gyur现行(非通达)·rgyal phran城王;含汉传暗引:辨中边论释释触/俱舍论四缘生心心所/科判摄颂;句法:X kyi dbang du byas pa=以…而言·kun nas nyon mongs↔rnam byang杂染↔清净成对·教证夹注不入平行文）
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
