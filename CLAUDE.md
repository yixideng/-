# 藏文佛教经典汉译 Agent —— 项目说明（供 AI 会话自动读取）

本仓库是一个**藏译汉佛经翻译 agent**。任何新的 Claude Code 会话进来，请先读本文件，
按下面的方式使用它——**不要凭自己的知识直接翻译，必须走本仓库的流水线**，
这样才能用上已有的词典、术语表和译者定稿的译例，保证译名统一。

## 这个 agent 是什么

它不是一个常驻服务，而是「脚本 + 数据」。翻译时运行 `agent/translator.py`，
它会自动：分段 → 查两本词典 → 套用术语表（强制统一译名）→ 检索相似历史译例
→ **注入笔记层（法义纲要 + 句法通则）** → 交给 Claude 出译文。详见 `PLAN.md` 与 `pipeline/README.md`。

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
```

术语表 `glossary/glossary.tsv` 与校正稿目录 `review/` **在 Git 里**，无需重建。

## 翻译一段藏文

```bash
# 只看检索到的资料（术语/词典/译例），核对召回质量：
python3 agent/translator.py --text "藏文…" --packet

# 完整翻译：
python3 agent/translator.py --file 待译.txt --out 译文.md
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
