"""流水线回归测试（标准库 unittest，无需联网/调模型）。

    python3 -m unittest discover tests -v

覆盖：术语分层择优、真实术语库关键裁定、查词优先级、全角标点、润色对齐、
法义按需节选、译例命名派生。依赖 data/processed 的用例在库缺失时自动跳过
（先跑 python3 pipeline/rebuild.py）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "pipeline"))

import tools  # noqa: E402
import translator as tr  # noqa: E402
import tmlib  # noqa: E402

E = tools._gloss_entry


class TestGlossaryResolve(unittest.TestCase):
    def test_user_beats_higher_freq_auto(self):
        es = [E("无间缘", 9, "宝性论大疏", 1), E("等无间缘〔四缘之一〕", 2, "校订本5.27｜用户裁定", 2)]
        zh, _f, multi = tools._resolve_gloss(es)
        self.assertFalse(multi)
        self.assertTrue(zh.startswith("等无间缘"))

    def test_user_beats_manual(self):
        es = [E("欲", 3, "宝性论大疏｜人工校正", 1), E("承许", 3, "用户裁定", 2)]
        zh, _f, multi = tools._resolve_gloss(es)
        self.assertFalse(multi)
        self.assertTrue(zh.startswith("承许"))

    def test_context_marked_becomes_multi_listing_all(self):
        es = [E("集会", 5, "宝性论大疏", 1), E("归摄（此语境非集会）", 1, "用户裁定", 2)]
        zh, _f, multi = tools._resolve_gloss(es)
        self.assertTrue(multi)
        self.assertIn("归摄", zh)
        self.assertIn("集会", zh)
        self.assertLess(zh.index("归摄"), zh.index("集会"))   # 用户义在前

    def test_two_user_senses_multi(self):
        es = [E("可欲", 2, "用户裁定", 1), E("承许", 3, "用户裁定", 2)]
        self.assertTrue(tools._resolve_gloss(es)[2])

    def test_supersede_same_core_forced(self):
        es = [E("坏苦（三苦之一）", 2, "用户裁定", 1), E("坏苦（6.6校正版）", 2, "校订本", 2)]
        zh, _f, multi = tools._resolve_gloss(es)
        self.assertFalse(multi)
        self.assertTrue(zh.startswith("坏苦"))

    def test_pure_auto_conflict_keeps_highest_freq(self):
        es = [E("分位", 15, "宝性论大疏", 1), E("暂时", 6, "宝性论大疏", 2)]
        self.assertEqual(tools._resolve_gloss(es)[:3:2], ("分位", False))

    def test_reference_only_excluded(self):
        es = [E("因此", 30, "宝性论大疏｜参考(校正命中0/101)", 1)]
        self.assertIsNone(tools._resolve_gloss(es))

    def test_reference_does_not_block_user(self):
        es = [E("实有", 9, "宝性论大疏｜参考", 1), E("谛实有", 2, "用户裁定", 2)]
        zh, _f, multi = tools._resolve_gloss(es)
        self.assertFalse(multi)
        self.assertTrue(zh.startswith("谛实有"))


class TestRealGlossary(unittest.TestCase):
    """真实术语库上的关键用户裁定（防回归）。"""

    @classmethod
    def setUpClass(cls):
        tools._glossary_cache = None
        cls.g = tools.load_glossary()

    def test_key_rulings(self):
        self.assertTrue(self.g["དེ་མ་ཐག་རྐྱེན"][0].startswith("等无间缘"))
        self.assertFalse(self.g["དེ་མ་ཐག་རྐྱེན"][2])
        zh, _f, multi = self.g["འདོད་པ"]
        self.assertTrue(multi)
        self.assertIn("承许", zh)
        self.assertIn("欲", zh)
        self.assertIn("意趣", self.g["དགོངས་པ"][0])
        self.assertTrue(self.g["འགྱུར་བའི་སྡུག་བསྔལ"][0].startswith("坏苦"))
        self.assertTrue(self.g["བྱེད་པ་པོ"][0].startswith("作者"))

    def test_demoted_not_in_packet(self):
        for bo in ("དེས་ན", "ཡོད་པ", "མེད་པ"):
            self.assertNotIn(bo, self.g)

    def test_no_user_ruling_shadowed(self):
        rows = [l.rstrip("\n").split("\t") for i, l in
                enumerate((ROOT / "glossary/glossary.tsv").read_text(encoding="utf-8").splitlines()) if i > 0 and l.strip()]
        lost = []
        for r in rows:
            if len(r) < 4 or not ("用户" in r[3] or "校订本" in r[3]):
                continue
            core = tools._CORE_CUT.split(r[1], 1)[0].strip()
            if r[0] in self.g and core not in self.g[r[0]][0]:
                lost.append((r[0], core))
        self.assertEqual(lost, [])


@unittest.skipUnless((ROOT / "data/processed/dict.sqlite").exists(), "字典库未建（先跑 rebuild.py）")
class TestDictPriority(unittest.TestCase):
    def test_sorted_by_priority(self):
        res = tools.lookup_dict("དགོངས་པ")
        ranks = [tools.DICT_PRIORITY.get(r["source"], 99) for r in res]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(res[0]["source"], "藏汉大辞典")


class TestFullwidth(unittest.TestCase):
    def test_cjk_lines_only(self):
        self.assertEqual(tr._fullwidth_cn("如是,彼云:有;问?答(甲)。"), "如是，彼云：有；问？答（甲）。")
        bo = "དགེ་སློང་དག (x)"
        self.assertEqual(tr._fullwidth_cn(bo), bo)
        self.assertIn("6.12", tr._fullwidth_cn("见6.12段,"))


class TestPolishMerge(unittest.TestCase):
    D = ("ཀ་ཁ་ག་ང་ཅ་ཆ།\n甲直译。\n\nཇ་ཉ་ཏ་ཐ་ད་ན།\n乙直译。\n\nཔ་ཕ་བ་མ་ཙ་ཚ།\n丙直译。")
    P = ("ཀ་ཁ་ག་ང་ཅ་ཆ།\n甲润色。\n\nཇ་ཉ་ཏ་ཐ་ད་ན།\n乙润色。\n\nཔ་ཕ་བ་མ་ཙ་ཚ།\n丙润色。")

    def test_exact(self):
        out, fb = tr._merge_polished(self.D, self.P)
        self.assertEqual(fb, 0)
        self.assertIn("乙润色", out)

    def test_missing_blank_lines(self):
        out, fb = tr._merge_polished(self.D, self.P.replace("\n\n", "\n"))
        self.assertEqual(fb, 0)

    def test_tibetan_drift_keeps_draft_tibetan(self):
        drifted = self.P.replace("ཇ་ཉ་ཏ་ཐ་ད་ན།", "ཇ་ཉ་ཏ་ཐ་ད།")
        out, fb = tr._merge_polished(self.D, drifted)
        self.assertEqual(fb, 0)
        self.assertIn("ཇ་ཉ་ཏ་ཐ་ད་ན།", out)          # 藏文行取直译稿原文
        self.assertNotIn("ཇ་ཉ་ཏ་ཐ་ད།\n", out)

    def test_missing_segment_falls_back(self):
        p = "ཀ་ཁ་ག་ང་ཅ་ཆ།\n甲润色。\n\nཔ་ཕ་བ་མ་ཙ་ཚ།\n丙润色。"
        out, fb = tr._merge_polished(self.D, p)
        self.assertEqual(fb, 1)
        self.assertIn("乙直译", out)
        self.assertIn("丙润色", out)


class TestSelectFayi(unittest.TestCase):
    def test_general_kept_and_summaries_capped(self):
        body = "# 法义\n\n## 一、通则\n通则内容\n\n" + "".join(
            f"## 5.{i} 纪要{i}\nཀ་ཁ{i} 内容{i}\n\n" for i in range(1, 12))
        out = tr.select_fayi(body, "ཀ་ཁ་ག")
        self.assertIn("## 一、通则", out)
        n = sum(1 for l in out.splitlines() if l.startswith("## 5."))
        self.assertLessEqual(n, 6)
        for i in (9, 10, 11):                            # 最近 3 节必在
            self.assertIn(f"## 5.{i} ", out)

    def test_small_body_unchanged(self):
        body = "## 一、通则\nx\n\n## 5.1 纪要\ny\n"
        self.assertEqual(tr.select_fayi(body, "ཀ"), body)


class TestTmNaming(unittest.TestCase):
    def test_ids(self):
        r = ROOT / "review"
        self.assertEqual(tmlib.tm_id(r / "gzhanstong_6.10_某题_parallel.txt"), "610")
        self.assertEqual(tmlib.tm_id(r / "gzhanstong_5.13a_某题_parallel.txt"), "513a")
        self.assertEqual(tmlib.tm_id(r / "gzhanstong_2.0_parallel.txt"), "2")
        self.assertEqual(tmlib.tm_id(r / "gzhanstong_reviewed_parallel.txt"), "reviewed")
        self.assertEqual(tmlib.tm_id(r / "gzhanstong_6.3_成立内之诸行刹那十四种生.txt"), "63")
        k = ROOT / "projects/kalacakra/review/kalacakra_46_鼻孔六坛城_parallel.txt"
        self.assertEqual(tmlib.tm_path(k, "kalacakra").name, "tm_kalacakra_46.jsonl")

    def test_every_parallel_has_tm(self):
        if not (ROOT / "data/processed").exists():
            self.skipTest("未重建")
        missing = [p.name for p in tmlib.parallels("gzhanstong") if not tmlib.tm_path(p).exists()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
