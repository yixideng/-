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
| `parse_dict.py` | 解析混编 HTML 词典 → JSONL；按来源分条，抽词头/来源/页码/词性/义项/标签/异体/例词 |
| `build_index.py` | JSONL → SQLite（entries 主表 + entries_fts 全文索引 + alt_map 异体映射） |
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

## 现状（藏汉大辞典）

- 记录数：78,607（藏汉大辞典 53,201 / 甘肃版藏汉词典 25,381 / 无来源标注 25）
- 解析耗时 ~13s，建库耗时 ~数秒，dict.sqlite ~78MB
- 验证：ཆོས/སངས་རྒྱས/སྟོང་པ་ཉིད/བྱང་ཆུབ་ཀྱི་སེམས 等佛学核心词均正确返回双来源释义

## 待办

- 第二本《格西曲扎藏文词典》：格式可能不同（藏文释义为主），
  上传后先探格式，再决定复用还是另写解析分支，建成独立的第二个索引。
