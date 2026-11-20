# 觉囊派祖师论著·整本翻译（`jonang` 项目）

与胜乘中观（`gzhanstong`）**共用全部设置**——法义／句法／文风笔记、翻译记忆、共享术语库、校正版统计——
只另有：

```
projects/jonang/
├── glossary.tsv     # 可选术语覆盖层（书中专名等；优先于共享库）
├── 待译/<书名>.txt   # 整本藏文原文（原样）
└── books/<书名>/    # 产出：_全译.md（藏汉对照）·_汉文.md·_质检汇总.md·chunks/
```

整本翻译、不校正回流。用法见仓库根 `CLAUDE.md`「整本翻译」节：

```bash
python3 pipeline/translate_book.py --book projects/jonang/待译/<书名>.txt --name <书名> --dry-run   # 切块·估价
python3 pipeline/translate_book.py --book projects/jonang/待译/<书名>.txt --name <书名>             # 开译（可断点续跑）
```
