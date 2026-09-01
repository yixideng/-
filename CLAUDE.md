# 藏文佛教经典汉译 Agent —— 项目说明（供 AI 会话自动读取）

本仓库是一个**藏译汉佛经翻译 agent**。任何新的 Claude Code 会话进来，请先读本文件，
按下面的方式使用它——**不要凭自己的知识直接翻译，必须走本仓库的流水线**，
这样才能用上已有的词典、术语表和译者定稿的译例，保证译名统一。

## 这个 agent 是什么

它不是一个常驻服务，而是「脚本 + 数据」。翻译时运行 `agent/translator.py`，
它会自动：分段 → 查两本词典 → 套用术语表（强制统一译名）→ 检索相似历史译例
→ **注入笔记层（法义纲要 + 句法通则）** → 交给 Claude 出译文。详见 `PLAN.md` 与 `pipeline/README.md`。

## 多项目（同一知识库，多本经论互不污染）

本仓库可**同时翻译多本经论**，用 `--project` 切换。设计＝**共享底座 + 分项目层**：

| 层 | 是否共享 | 说明 |
|---|---|---|
| 两本词典 + 流水线代码 | **共享** | 通用，两项目都用 |
| 术语库 `glossary/glossary.tsv` | **共享（只读基础）** | 积累的术语校正，新项目直接复用 |
| 翻译记忆(译例)/笔记(法义·句法·文风)/校订本/科判 | **各项目独立** | 文风义理迥异，隔离防带偏 |
| 项目新增术语 | **各项目覆盖层** | 写进 `projects/<名>/glossary.tsv`，**不写共享库**（这样互不影响）|

已建项目：
- **`gzhanstong`（默认）**＝胜乘中观(他空大中观)：沿用 `notes/` `review/` `glossary/glossary.tsv` 与 `data/processed/tm_gzhanstong_*`。**不带 --project 时行为与原来完全一致。**
- **`kalacakra`**＝时轮根本续：`projects/kalacakra/{notes,review,source_texts,glossary.tsv}`，译例存 `data/processed/tm_kalacakra_*`。共享词典与术语库，但笔记/译例/新术语独立。

用法：`python3 agent/translator.py --project kalacakra --file 待译.txt --out 译文.md`
（回流时 align.py 输出到 `data/processed/tm_kalacakra_*.jsonl`，校订本/平行文放 `projects/kalacakra/review/`，
时轮专用术语加到 `projects/kalacakra/glossary.tsv`。注册表见 `agent/tools.py` 的 `PROJECTS`。）

**校正会分四类归档，各有各的"家"，放对才会扩散到后续翻译：**

| 校正类型 | 归档处 | 触发方式 |
|---|---|---|
| 术语（词→词） | `glossary/glossary.tsv` | 藏文词精确匹配（含格助词剥离） |
| 译例·文风（整句） | `review/*_parallel.txt` → 翻译记忆 | 音节相似度检索 |
| **法义/教义**（宗见、破立归属、义理取向） | `notes/法义.md` | **恒常注入 prompt** |
| **句法/文法**（结构解析通则） | `notes/句法.md` | **恒常注入 prompt** |

`notes/` 两文件都进 Git、以用户为权威；由 `translator.py` 每次翻译恒常注入（不靠相似度），
故文法/义理类校正（"换了词也照样成立"的规律）也能扩散——这类校正**不要**只塞进术语表或译例。

## 会话开始时：先确认索引在不在（容器是临时的）

词典库/翻译记忆是**可再生的大文件**，不进 Git，容器重置后会消失。开工前先检查：

```bash
ls -lh data/processed/dict.sqlite data/processed/gexi.sqlite 2>/dev/null
```

**若不存在，先重建**（原始素材在本仓库的 GitHub Release，持久保存）：

```bash
# 1. 藏汉大辞典
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488012632" \
  -o data/raw/dictionaries/zhdcd_full.txt
python3 pipeline/parse_dict.py data/raw/dictionaries/zhdcd_full.txt --out data/processed/dict.jsonl
python3 pipeline/build_index.py data/processed/dict.jsonl --out data/processed/dict.sqlite

# 2. 格西曲扎藏文词典
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488022264" \
  -o data/raw/dictionaries/gexi_full.txt
python3 pipeline/parse_gexi.py data/raw/dictionaries/gexi_full.txt --out data/processed/gexi.jsonl
python3 pipeline/build_index.py data/processed/gexi.jsonl --out data/processed/gexi.sqlite

# 3. 译例（翻译记忆）
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488042512" \
  -o data/raw/parallel/sample1_baoxinglun.txt
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488043677" \
  -o data/raw/parallel/sample2_zhongguan.txt
python3 pipeline/align.py data/raw/parallel/sample1_baoxinglun.txt --source "宝性论大疏" --out data/processed/tm_baoxinglun.jsonl
python3 pipeline/align.py data/raw/parallel/sample2_zhongguan.txt --source "极广胜乘中观决定" --out data/processed/tm_zhongguan.jsonl
# 用户校订·文风范本（对照源在 review/，进 Git）
python3 pipeline/align.py review/gzhanstong_reviewed_parallel.txt --source "他空中观校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_reviewed.jsonl
python3 pipeline/align.py review/gzhanstong_2.0_parallel.txt --source "他空中观2.0论体校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_2.jsonl
python3 pipeline/align.py review/gzhanstong_2.2_parallel.txt --source "他空中观2.2广说校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_22.jsonl
python3 pipeline/align.py review/gzhanstong_2.3_异门_parallel.txt --source "他空中观2.3异门校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_23.jsonl
python3 pipeline/align.py review/gzhanstong_2.4_蕴界处_parallel.txt --source "他空中观品二蕴界处校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_24.jsonl
python3 pipeline/align.py review/gzhanstong_2.5_行蕴_parallel.txt --source "他空中观品二行蕴校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_25.jsonl
python3 pipeline/align.py review/gzhanstong_2.6_性相法_parallel.txt --source "他空中观品二性相法校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_26.jsonl
python3 pipeline/align.py review/gzhanstong_2.7_假立法续_parallel.txt --source "他空中观品二假立法续校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_27.jsonl
python3 pipeline/align.py review/gzhanstong_2.8_无实法道_parallel.txt --source "他空中观品二无实法与道校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_28.jsonl
python3 pipeline/align.py review/gzhanstong_2.9_五乘无为果_parallel.txt --source "他空中观品二五乘无为果校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_29.jsonl
python3 pipeline/align.py review/gzhanstong_2.10_五基_parallel.txt --source "他空中观品二五基校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_210.jsonl
python3 pipeline/align.py review/gzhanstong_2.11_四谛_parallel.txt --source "他空中观品二四谛校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_211.jsonl
python3 pipeline/align.py review/gzhanstong_2.12_品二末_parallel.txt --source "他空中观品二末段校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_212.jsonl
python3 pipeline/align.py review/gzhanstong_3.2_常义周遍义_parallel.txt --source "他空中观品三常义周遍义校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_32.jsonl
python3 pipeline/align.py review/gzhanstong_3.3_觉义一切相_parallel.txt --source "他空中观品三觉义一切相校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_33.jsonl
python3 pipeline/align.py review/gzhanstong_3.4_一切相离戏不杂_parallel.txt --source "他空中观品三一切相离戏不杂校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_34.jsonl
python3 pipeline/align.py review/gzhanstong_3.5_双运种界龙树会通九相_parallel.txt --source "他空中观品三双运种界龙树会通九相校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_35.jsonl
python3 pipeline/align.py review/gzhanstong_3.6_断疑常义周遍自证_parallel.txt --source "他空中观品三断疑常义周遍自证校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_36.jsonl
python3 pipeline/align.py review/gzhanstong_3.7_破立缘起双运种界现相_parallel.txt --source "他空中观品三破立缘起双运种界现相校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_37.jsonl
python3 pipeline/align.py review/gzhanstong_3.8_法界离时种界遍义破三错解_parallel.txt --source "他空中观品三法界离时种界遍义破三错解校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_38.jsonl
python3 pipeline/align.py review/gzhanstong_3.9_阿赖耶智涅槃轮回基果非新生_parallel.txt --source "他空中观品三阿赖耶智涅槃轮回基果非新生校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_39.jsonl
python3 pipeline/align.py review/gzhanstong_4.1_真世俗唯识八识聚三十颂略标_parallel.txt --source "他空中观品四真世俗唯识八识聚三十颂略标校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_41.jsonl
python3 pipeline/align.py review/gzhanstong_4.2_三识体性异熟种子阿赖耶三相_parallel.txt --source "他空中观品四三识体性异熟种子阿赖耶三相校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_42.jsonl
python3 pipeline/align.py review/gzhanstong_4.3_心意识三名五遍行无覆无记转依_parallel.txt --source "他空中观品四心意识三名五遍行无覆无记转依校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_43.jsonl
python3 pipeline/align.py review/gzhanstong_4.4_释末那六转识八识俱起意识界限_parallel.txt --source "他空中观品四释末那六转识八识俱起意识界限校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_44.jsonl
python3 pipeline/align.py review/gzhanstong_4.5_因果次第教理成立阿赖耶引经_parallel.txt --source "他空中观品四因果次第教理成立阿赖耶引经校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_45.jsonl
python3 pipeline/align.py review/gzhanstong_4.6_理证成立阿赖耶衣罩喻还灭心性清净引密严经_parallel.txt --source "他空中观品四理证成立阿赖耶衣罩喻还灭心性清净引密严经校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_46.jsonl
python3 pipeline/align.py review/gzhanstong_4.7_外境不成乳酪功德喻十八部异名龙树菩提心释成立阿赖耶_parallel.txt --source "他空中观品四外境不成乳酪功德喻十八部异名龙树菩提心释成立阿赖耶校订本(用户认可·文风范本)" --out data/processed/tm_gzhanstong_47.jsonl
```

术语表 `glossary/glossary.tsv` 与校正稿目录 `review/` **在 Git 里**，无需重建。

## 翻译一段藏文

```bash
# 只看检索到的资料（术语/词典/译例），核对召回质量：
python3 agent/translator.py --text "藏文…" --packet

# 完整翻译（默认两阶段：准确直译 → 定稿体润色）：
python3 agent/translator.py --file 待译.txt --out 译文.md
#   ↑ 默认 --polish：第一遍注入 prompts/translate.md+notes 三层(法义/句法/文风)+术语/词典/译例出直译；
#     第二遍按 prompts/polish.md+notes/文风.md 只改行文出定稿体；段数校验兜底(漂移则退回直译)。
#     纯直译稿会一并另存为 *_直译.md（供日后「机器稿↔校正版」diff 提炼文风）。
python3 agent/translator.py --file 待译.txt --out 译文.md --no-polish   # 只要纯直译（跳过润色遍）
# 选模型：--model claude-opus-4-8（主力，性价比高）或 --model claude-fable-5（难点/终校）
```

## 如何证明「用了本 agent」而非凭空翻译

调用 agent 一定会执行 `python3 agent/translator.py`，且资料包里含
「术语约束 / 词典释义 / 参考译例」。**若没有运行该脚本，就是没用本仓库的资源——不要这样做。**

## 校正回流（越用越准）

人工校改后的稿子放 `review/`；术语层面的更正并入 `glossary/glossary.tsv`。
这两处是核心人工资产，都在 Git 里，永久保存。

## 现状与待办

- ✅ 两本词典入库、术语表 v0（1054 条）、译例对齐、翻译流水线跑通
- ⬜ 审校稿导出与回流脚本；评测基线
- ⬜（可选）加藏文/汉文大藏经，做「暗引」比对与玄奘/鸠摩罗什对应译文
