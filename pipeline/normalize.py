"""藏文文本规范化工具。

所有藏文入库前必须过一遍 nfc()，否则组合字符编码序列不唯一，
检索时同一个词会失配。参见 PLAN.md 第四节。
"""
import unicodedata

TSHEG = "་"          # ་ 音节点
SHAD = "།"           # ། 单垂符
NYIS_SHAD = "༎"      # ༎ 双垂符

# 藏文 Unicode 区块：主区 0F00–0FFF
_BO_RANGES = ((0x0F00, 0x0FFF),)


def nfc(s: str) -> str:
    """Unicode NFC 规范化。入库/查询前一律调用。"""
    return unicodedata.normalize("NFC", s)


def is_tibetan_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _BO_RANGES)


def has_tibetan(s: str) -> bool:
    return any(is_tibetan_char(c) for c in s)


def strip_edge_shad(s: str) -> str:
    """去掉词头两端的 shad（།）和空白，如 '།ཀ་ཀ།' -> 'ཀ་ཀ'。"""
    return s.strip().strip(SHAD + NYIS_SHAD).strip().strip(TSHEG).strip()


def lookup_key(s: str) -> str:
    """生成词典查询归一键：NFC + 去两端 shad/tsheg/空白。

    注意：不剥格助词。格助词剥离属于查询期的形态还原（见 morph.py 规划），
    入库键保持词条本来面貌。
    """
    return strip_edge_shad(nfc(s))


def clean_ws(s: str) -> str:
    """把连续空白（含藏文里夹杂的换行）压成单空格并去首尾。"""
    return " ".join(s.split())
