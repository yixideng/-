# 时轮根本续（Kālacakra）翻译项目

与胜乘中观（他空大中观）**同仓库、同流水线、同词典、同共享术语库**，但译例/笔记/新术语**独立隔离**，
互不污染。项目机制见仓库根 `CLAUDE.md`「多项目」一节与 `agent/tools.py` 的 `PROJECTS` 注册表。

## 目录

```
projects/kalacakra/
├── glossary.tsv         # 时轮术语覆盖层（专用译名·优先于共享库；不写共享 glossary/glossary.tsv）
├── notes/
│   ├── 法义.md          # 时轮义理纲要（恒常注入）
│   ├── 句法.md          # 时轮句法通则（恒常注入）
│   └── 文风.md          # 时轮偈颂译风（恒常注入 + 润色遍依据）
├── review/              # 校订本 + 平行文（进 git，核心人工资产）
└── source_texts/        # 机器草稿(原文/译文)——gitignore，可再生
```
翻译记忆存 `data/processed/tm_kalacakra_*.jsonl`（gitignore，可从 review/ 平行文 align 重建）。

## 翻译一段

```bash
python3 agent/translator.py --project kalacakra --file 待译.txt --out 译文.md
python3 agent/translator.py --project kalacakra --text "藏文…" --packet   # 只看资料包
```

## 校正回流（四层，与主项目同法，但都落在本项目）

| 校正类型 | 归档处 |
|---|---|
| 术语（词→词） | `projects/kalacakra/glossary.tsv` |
| 译例·文风（整句） | `projects/kalacakra/review/*_parallel.txt` → `data/processed/tm_kalacakra_*.jsonl` |
| 法义/教义 | `projects/kalacakra/notes/法义.md` |
| 句法/文法 | `projects/kalacakra/notes/句法.md` |

回流译例：
```bash
python3 pipeline/align.py projects/kalacakra/review/<名>_parallel.txt \
  --source "时轮<章节>校订本(用户认可·文风范本)" \
  --out data/processed/tm_kalacakra_<名>.jsonl
```
（`tm` 走 glob `data/processed/tm_kalacakra_*.jsonl`，新文件自动纳入，无需改 tools.py。）

## 与胜乘中观的关系

- **共享**：两本词典、共享术语库 `glossary/glossary.tsv`（只读复用积累术语，如"龙树/如来藏/胜义"）。
- **隔离**：时轮的译例/笔记/新术语只在本项目生效，**绝不影响胜乘中观**；反之胜乘中观的论体译例也不会检索进时轮偈颂。
- 时轮特有术语若与共享库同一藏文词需另译，写进本项目 `glossary.tsv` 覆盖层即可（仅对本项目生效）。
