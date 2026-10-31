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
            if "参考" in r[3]:             # 已被新裁定明令取代（如 4.10「身见」、5.1「执取方式」）·有意退役
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
        out, fb, _ = tr._merge_polished(self.D, self.P)
        self.assertEqual(fb, 0)
        self.assertIn("乙润色", out)

    def test_missing_blank_lines(self):
        out, fb, _ = tr._merge_polished(self.D, self.P.replace("\n\n", "\n"))
        self.assertEqual(fb, 0)

    def test_tibetan_drift_keeps_draft_tibetan(self):
        drifted = self.P.replace("ཇ་ཉ་ཏ་ཐ་ད་ན།", "ཇ་ཉ་ཏ་ཐ་ད།")
        out, fb, _ = tr._merge_polished(self.D, drifted)
        self.assertEqual(fb, 0)
        self.assertIn("ཇ་ཉ་ཏ་ཐ་ད་ན།", out)          # 藏文行取直译稿原文
        self.assertNotIn("ཇ་ཉ་ཏ་ཐ་ད།\n", out)

    def test_missing_segment_falls_back(self):
        p = "ཀ་ཁ་ག་ང་ཅ་ཆ།\n甲润色。\n\nཔ་ཕ་བ་མ་ཙ་ཚ།\n丙润色。"
        out, fb, _ = tr._merge_polished(self.D, p)
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



# ===== 外部评审修复（失败发声·词典选词·IDF检索·质检·多义五五开）=====
import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402


class TestLoudFailures(unittest.TestCase):
    def _fake_cli(self, body):
        d = tempfile.mkdtemp()
        p = Path(d) / "claude"
        p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return d

    def _run_with(self, d):
        old = os.environ["PATH"]
        os.environ["PATH"] = d + os.pathsep + old
        try:
            return tr._run_claude("x", "", "g")
        finally:
            os.environ["PATH"] = old

    def test_nonzero_exit_raises_not_returns_stderr(self):
        d = self._fake_cli('echo "API Error: overloaded" >&2\nexit 1')
        with self.assertRaises(tr.ModelCallError):
            self._run_with(d)

    def test_empty_output_raises(self):
        with self.assertRaises(tr.ModelCallError):
            self._run_with(self._fake_cli("exit 0"))

    def test_is_error_json_raises(self):
        d = self._fake_cli('echo \'{"is_error": true, "result": "Credit balance too low"}\'')
        with self.assertRaises(tr.ModelCallError):
            self._run_with(d)

    def test_ok_json_returns_result_and_records_usage(self):
        d = self._fake_cli('echo \'{"result": "译文", "usage": {"input_tokens": 10, '
                           '"cache_creation_input_tokens": 5, "cache_read_input_tokens": 0, '
                           '"output_tokens": 3}, "total_cost_usd": 0.01}\'')
        n = len(tr.USAGE)
        self.assertEqual(self._run_with(d), "译文")
        self.assertEqual(tr.USAGE[-1]["in"], 15)
        self.assertEqual(len(tr.USAGE), n + 1)

    def test_prompt_caching_disabled_for_inner_calls(self):
        """CLI 默认 1 小时缓存写入＝2 倍输入价且从无复用：内层调用须关缓存。"""
        d = self._fake_cli('echo "{\\"result\\": \\"$DISABLE_PROMPT_CACHING\\"}"')
        self.assertEqual(self._run_with(d), "1")

    def test_resource_status_reports_missing_dict(self):
        saved = tools.DICT_DBS
        try:
            tools.DICT_DBS = [("不存在的字典", ROOT / "data/processed/__nope__.sqlite")]
            self.assertTrue(any("不存在的字典" in m for m in tools.resource_status()["missing"]))
        finally:
            tools.DICT_DBS = saved


class TestDictSelection(unittest.TestCase):
    def test_rarest_kept_common_dropped_with_footer(self):
        saved, saved_max = tools._tm_corpus, tr.DICT_MAX
        try:
            tools._tm_corpus = "ཀཀ " * 50 + "ཁཁ " * 20
            tr.DICT_MAX = 1
            mk = lambda s: [{"source": "藏汉大辞典", "senses": [s]}]
            out = tr.render_dict_hits([("ཀཀ", mk("常见")), ("གག", mk("罕见")), ("ཁཁ", mk("次常见"))])
            self.assertTrue(any("གག" in l for l in out))
            self.assertFalse(any(l.startswith("- ཀཀ") for l in out))
            self.assertIn("另有 2 个较常见词从略", out[-1])
        finally:
            tools._tm_corpus, tr.DICT_MAX = saved, saved_max


@unittest.skipUnless(list((ROOT / "data/processed").glob("tm_gzhanstong_*.jsonl")), "译例未建")
class TestIdfRetrieval(unittest.TestCase):
    def test_rare_word_wins_over_boilerplate(self):
        q = ("དཔེར་ན། འཕགས་པ་ཤཱ་རིའི་བུས་ཆོས་བསྟན་ཞེས་བརྗོད་དགོས་པ་ནི། དོན་ལ་དེའི་གཟུགས་དང༌། "
             "ཚོར་བ་དང༌། འདུ་ཤེས་དང༌། འདུ་བྱེད་དང༌། རྣམ་པར་ཤེས་པ་སྟེ། ཕུང་པོ་ལྔ")
        top = tools.search_tm(q, k=1)[0]
        self.assertTrue("舍利弗" in top["zh"] or "舍利子" in top["zh"], top["zh"][:60])   # 6.12 校正版回流后同句译例居首


class TestQaAndShrink(unittest.TestCase):
    BO = "ཀ་ཁ་ག་ང་ཅ་ཆ་ཇ་ཉ་ཏ་ཐ་ད་ན་པ་ཕ་བ་མ་ཙ་ཚ་ཛ་ཝ།"

    def test_swallowed_segment_flagged(self):
        iss = tr.qa_check(self.BO + "\n甲。")
        self.assertTrue(any("疑漏译" in x for x in iss))

    def test_normal_length_not_flagged(self):
        iss = tr.qa_check(self.BO + "\n" + "译" * 20 + "。")
        self.assertFalse(any("疑漏译" in x for x in iss))

    def test_polish_shrink_falls_back(self):
        d = self.BO + "\n" + "直" * 40 + "。"
        p = self.BO + "\n" + "润" * 10 + "。"
        out, fb, notes = tr._merge_polished(d, p)
        self.assertEqual(fb, 1)
        self.assertIn("直" * 40, out)
        self.assertTrue(any("疑吞句" in n for n in notes))


class TestNearTieAuto(unittest.TestCase):
    def test_near_tie_auto_becomes_multi(self):
        es = [E("体性", 39, "宝性论大疏", 1), E("自体", 31, "宝性论大疏", 2)]
        self.assertTrue(tools._resolve_gloss(es)[2])

    def test_clear_auto_winner_forced(self):
        es = [E("世俗", 65, "宝性论大疏", 1), E("俗谛", 14, "宝性论大疏", 2)]
        self.assertFalse(tools._resolve_gloss(es)[2])


class TestNoteGating(unittest.TestCase):
    NOTE = ("# 头\n> 说明里举例 `<!-- 状态：废止｜取代：§9 -->` 不算\n\n"
            "## 1. 通则\n常驻内容\n\n"
            "## 2. 专项\n<!-- 触发：ལྡོག་ཆ|ཐལ -->\n专项内容\n\n"
            "## 3. 旧规\n<!-- 状态：废止｜取代：§1 -->\n旧内容\n\n"
            "## 4. 新规\n<!-- 状态：观察 -->\n观察内容\n")

    def test_untagged_always_and_trigger_miss_reported(self):
        body, rep = tr.gate_sections(self.NOTE, "བུམ་པ་ཡོད།", "句法.md")
        self.assertIn("常驻内容", body)
        self.assertNotIn("专项内容", body)
        self.assertIn("未触发从略 1 节（§2）", rep)
        self.assertIn("从略 §2", body)            # 资料包内亦明示，漏注入可见

    def test_trigger_hit_with_tsheg_variant(self):
        body, rep = tr.gate_sections(self.NOTE, "ངོ་བོ་གཅིག་ཀྱང་ལྡོག༌ཆ་ཐ་དད།", "句法.md")
        self.assertIn("专项内容", body)
        self.assertIn("专项触发 1 节（§2）", rep)

    def test_retired_excluded_watch_labelled(self):
        body, rep = tr.gate_sections(self.NOTE, "", "句法.md")
        self.assertNotIn("旧内容", body)
        self.assertIn("已废止不注入 1 节（§3）", rep)   # 正文里举例的注释不算
        self.assertIn("观察中", body)

    def test_real_notes_audit_clean(self):
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "pipeline/audit_notes.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-800:])

    def test_core_rules_always_on(self):
        """常驻通则（殿后前移、工具格、尚简、交付铁律）不得因无触发而缺席。"""
        syn = (ROOT / "notes/句法.md").read_text(encoding="utf-8")
        wf = (ROOT / "notes/文风.md").read_text(encoding="utf-8")
        b1, _ = tr.gate_sections(syn, "བུམ་པ་ཡོད།")
        b2, _ = tr.gate_sections(wf, "བུམ་པ་ཡོད།")
        self.assertIn("## §48", b1)
        self.assertIn("## §51", b1)
        for h in ("## 13.", "## 14.", "## 交付形态铁律"):
            self.assertIn(h, b2)


class TestReflow611612(unittest.TestCase):
    def test_self_listed_senses_are_multi(self):
        """单条词头自列「A｜B（按语境…）」即多义，不得只取首义强制。"""
        es = [E("我想｜我所之想（按语境：缘自蕴＝我想）", 2, "校正版·用户裁定", 1)]
        self.assertTrue(tools._resolve_gloss(es)[2])
        es = [E("能作缘（功用缘）｜俱有缘（按语境：略称时）", 2, "用户裁定", 1)]   # 「｜」在括注之后
        self.assertTrue(tools._resolve_gloss(es)[2])
        es = [E("自在（一般义；按语境作「自在转」｜勿删转）", 2, "用户裁定", 1)]   # 「｜」只在括注内→非自列多义
        self.assertFalse(tools._resolve_gloss(es)[2])

    def test_brackets_unified_to_parens(self):
        self.assertEqual(tr._fullwidth_cn("若〔我〕实有"), "若（我）实有")
        self.assertEqual(tr._fullwidth_cn("〔བོད〕"), "〔བོད〕")      # 无汉字行不动

    def test_rulings_land(self):
        g = tools.load_glossary()
        self.assertEqual(g["རེས་འགའ"][0].split("／")[0], "有时")
        self.assertFalse(g["རེས་འགའ"][2])
        self.assertTrue(g["དགོངས་གཞི"][0].startswith("意趣"))
        self.assertTrue(g["དབང་བསྒྱུར"][2])                 # 主宰｜自在转 按语境
        self.assertEqual(g["འཇིག་ལྟ"][0].split("（")[0], "萨迦耶见")   # 全书统一（用户裁定·取代 4.10「身见」）
        self.assertFalse(g["འཇིག་ལྟ"][2])
        self.assertEqual(g["ཕུང་གསུམ་པ"][0].split("（")[0], "第三聚")            # 6.11 用户裁定
        self.assertTrue(g["བརྟགས་ཏེ་དགག་པ"][0].startswith("观察而遮"))
        self.assertTrue(g["འཛིན་སྟངས"][0].startswith("行相（执取相）"))     # 6.13 用户裁定·取代「执取方式」
        self.assertFalse(g["འཛིན་སྟངས"][2])


class TestFullwidthInParallels(unittest.TestCase):
    def test_no_half_width_punct_in_corrected_chinese(self):
        """全部校正版平行文汉译行无半角标点（全角铁律）；新回流时 reflow.py 亦当场提示。"""
        sys.path.insert(0, str(ROOT / "pipeline"))
        import reflow
        bad = [(p.name.split("_")[1], h) for p in (ROOT / "review").glob("gzhanstong_*_parallel.txt")
               for h in reflow.half_width_hits(p)]
        self.assertEqual(bad, [])


class TestSegmentation(unittest.TestCase):
    LONG = "དེ་ནི་ཡིན་ནོ། " * 10       # 凑超长段（>16 分句），触发兜底切分

    def test_no_cut_before_quote_marker(self):
        """终结词后紧跟 ཞེས/སྙམ（引语续接）不算句末：6.13「…བདེའོ། །…ལོ། །སྙམ་དུ」曾被腰斩。"""
        t = self.LONG + "བདག་བདེའོ། །བདག་སྡུག་བསྔལ་ལོ། །སྙམ་དུ་སེམས་པ་ཡང་མི་རིགས་སོ། །" + "དེ་ནི་ཡིན་ནོ། " * 6
        segs = tr.split_segments(t)
        self.assertFalse(any(s.rstrip().endswith("བསྔལ་ལོ།") for s in segs), segs)

    def test_heading_starts_segment_and_dangling_heading_carried(self):
        """科判标题领起新组；段末悬空标题挪到下一段开头（6.13「第四科」曾粘在上段末）。"""
        t = (self.LONG + "དེ་ནི་ཡིན་ནོ། " * 8 + "དོན་ཚན་བཞི་པ་ཚོགས་པ་ལ་བརྟགས་ཏེ་དགག་པ་ནི།\n"
             "དཀོན་བརྩེགས་ལས་བསྟན་པ་ལྟར་རོ།")
        segs = tr.split_segments(t)
        self.assertTrue(segs[-1].startswith("དོན་ཚན་བཞི་པ"), segs[-1][:30])
        self.assertFalse(any(s.endswith("དགག་པ་ནི།") for s in segs[:-1]))

    def test_short_paragraph_kept_whole(self):
        self.assertEqual(len(tr.split_segments("གཉིས་པ་ནི། ཡིན་ནོ། །ཞེས་སོ། །")), 1)

    def test_heading_only_line_kept(self):
        """用户把标题单列一行者照旧自成一组（6.12「第五科」「复广释彼义」皆单列）。"""
        segs = tr.split_segments("གཉིས་པ་སྔ་ཕྱི་ལ་བརྟགས་ཏེ་དགག་པ་ནི།\nསྐྱེས་བུ་ལྷས་བྱིན་ཡིན་ནོ།")
        self.assertEqual(len(segs), 2)


if __name__ == "__main__":
    unittest.main()
