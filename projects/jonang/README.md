# 觉囊派祖师论著·整本翻译（`jonang` 项目）

**轻量模式**（用户裁定·2026-11）：翻译以模型自身学识为主、资料为辅。与胜乘中观共用译例与共享术语库（只读），
但用自己的指令与笔记，原系统规则一概不动：

- `prompts/translate.md`：精简指令（只留用户裁定术语、专名与吉祥语、存疑标注、宗见护栏、输出格式）；`prompts/文体.md`：本书文体（标点·语体·偈颂）。
- `notes/法义护栏.md`：摘自 `notes/法义.md` 一～四、六（他空宗见框架），原文照录。
- 代码开关（`agent/tools.py` `PROJECTS["jonang"]`）：`force_only_user` 仅用户裁定/校订本术语强制；`polish: False` 一遍出稿；
  `verse_split` 偈颂无终结词时四句一颂切段；`dict_skt_fallback` 梵文转写（སྭཱ་སྟི）去长音再查词；`lite` 资料包措辞改为旁参、不列逐字参考。
- **恢复原设置**：删去上述 lite 诸键、`notes` 改回 `notes/` 三件即可。

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
