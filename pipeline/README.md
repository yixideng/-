# 词典处理流水线

把原始词典（Word 导出的混编 HTML/TXT）变成 Agent 可瞬间查询的 SQLite 库。

## 数据流

```
原始词典.txt ──parse_dict.py──▶ dict.jsonl ──build_index.py──▶ dict.sqlite
（GitHub Release，                 结构化词条              可检索查词库
 84MB，持久保存）                （每来源一条）           （FTS5 + 索引）
                                                              │
                                                      lookup.py / Agent 查询
```

原始 `.txt` 与生成的 `.jsonl` / `.sqlite` 都在 `.gitignore` 里（体量大），
**不进仓库**；只有脚本进仓库。原始文件持久存放在 GitHub Release，
容器重置后按下面「重建」一步即可恢复整套。

## 各脚本

| 脚本 | 作用 |
|---|---|
| `normalize.py` | 藏文 NFC 规范化、shad/tsheg 归一、查询键生成（被其他脚本引用） |
| `parse_dict.py` | 解析**藏汉大辞典**（混编 Word-HTML）→ JSONL；按来源分条，抽词头/来源/页码/词性/义项/标签/异体/例词 |
| `parse_gexi.py` | 解析**格西曲扎藏文词典**（简单 HTML）→ JSONL；体例不同（Ⅰ/Ⅱ、1./2. 义项，﹝梵﹞﹝达﹞标注，@页码），输出同一 Entry schema |
| `build_index.py` | JSONL → SQLite（entries 主表 + entries_fts 全文索引 + alt_map 异体映射），两本词典各建一个独立库 |
| `lookup.py` | 命令行查词；也是 Agent 端 `lookup_dict` 工具的参考实现（精确→异体→前缀三级兜底） |
| `make_sample.py` | 从大文件等距抽样，供格式核对 |

## 重建整套库（容器重置后或词典更新后）

```bash
# 1. 从 Release 下载原始词典（需 GITHUB_TOKEN 环境变量）
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488012632" \
  -o data/raw/dictionaries/zhdcd_full.txt

# 2. 解析
python3 pipeline/parse_dict.py data/raw/dictionaries/zhdcd_full.txt \
  --out data/processed/dict.jsonl --stats

# 3. 建库
python3 pipeline/build_index.py data/processed/dict.jsonl \
  --out data/processed/dict.sqlite

# 4. 试查
python3 pipeline/lookup.py "བྱང་ཆུབ་ཀྱི་སེམས"
```

## 现状（两本词典均已入库）

**藏汉大辞典** → `dict.sqlite`（~78MB，Release asset id 488012632）
- 78,607 条（藏汉大辞典 53,201 / 甘肃版藏汉词典 25,381 / 无来源标注 25）

**格西曲扎藏文词典** → `gexi.sqlite`（~15MB，Release asset id 488022264）
- 25,363 条（含标签 6,251 / 含页码 25,201）

两库独立，查询时并查、互补：甘肃版最简明、藏汉大辞典下定义、格西曲扎补同义与梵文对应。
验证：ཆོས/སངས་རྒྱས/སྟོང་པ་ཉིད/བྱང་ཆུབ་ཀྱི་སེམས 等佛学核心词均正确返回。

## 重建格西曲扎库

```bash
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/yixideng/-/releases/assets/488022264" \
  -o data/raw/dictionaries/gexi_full.txt
python3 pipeline/parse_gexi.py data/raw/dictionaries/gexi_full.txt --out data/processed/gexi.jsonl --stats
python3 pipeline/build_index.py data/processed/gexi.jsonl --out data/processed/gexi.sqlite
python3 pipeline/lookup.py --db data/processed/gexi.sqlite "སངས་རྒྱས"
```
