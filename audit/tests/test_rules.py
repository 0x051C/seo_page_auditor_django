"""
Rule tests. SimpleTestCase: no database, because the rules are pure functions.
Each rule has a test for when it fires and one for the boundary where it stops.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from audit import rules


def metric(impressions=1000, ctr=0.05, position=2.0):
    return SimpleNamespace(impressions=impressions, ctr=ctr, position=position)


def check(status_code=200, title="A good title", meta_description="A description.", h1_count=1, word_count=800):
    return SimpleNamespace(
        status_code=status_code, title=title, meta_description=meta_description, h1_count=h1_count, word_count=word_count
    )


class LowCtrTests(SimpleTestCase):
    def test_triggers_on_many_impressions_and_low_ctr(self):
        finding = rules.low_ctr(impressions=500, ctr=0.0149)
        self.assertEqual(finding.rule, rules.LOW_CTR)
        self.assertIn("1.49%", finding.detail)

    def test_edge_ctr_of_exactly_1_5_percent_is_fine(self):
        self.assertIsNone(rules.low_ctr(impressions=5000, ctr=0.015))

    def test_edge_499_impressions_is_too_few_to_judge(self):
        self.assertIsNone(rules.low_ctr(impressions=499, ctr=0.0))


class StrikingDistanceTests(SimpleTestCase):
    def test_triggers_between_positions_4_and_10(self):
        self.assertEqual(rules.striking_distance(impressions=200, position=7.3).rule, rules.STRIKING_DISTANCE)

    def test_edge_positions_4_and_10_are_included(self):
        self.assertIsNotNone(rules.striking_distance(impressions=200, position=4.0))
        self.assertIsNotNone(rules.striking_distance(impressions=200, position=10.0))

    def test_edge_just_outside_the_range(self):
        self.assertIsNone(rules.striking_distance(impressions=5000, position=3.99))
        self.assertIsNone(rules.striking_distance(impressions=5000, position=10.01))

    def test_edge_199_impressions_is_too_few(self):
        self.assertIsNone(rules.striking_distance(impressions=199, position=6.0))


class MissingTitleTests(SimpleTestCase):
    def test_triggers_on_empty_title(self):
        self.assertEqual(rules.missing_title("").rule, rules.MISSING_TITLE)

    def test_edge_whitespace_only_title_counts_as_missing(self):
        self.assertIsNotNone(rules.missing_title("   \n"))

    def test_edge_one_character_title_is_present(self):
        self.assertIsNone(rules.missing_title("A"))


class TitleTooLongTests(SimpleTestCase):
    def test_triggers_over_60_characters(self):
        finding = rules.title_too_long("x" * 61)
        self.assertEqual(finding.rule, rules.TITLE_TOO_LONG)
        self.assertIn("61 characters", finding.detail)

    def test_edge_exactly_60_characters_is_fine(self):
        self.assertIsNone(rules.title_too_long("x" * 60))

    def test_edge_empty_title_is_not_too_long(self):
        # An empty title is MISSING_TITLE's job; it should not also be flagged here.
        self.assertIsNone(rules.title_too_long(""))


class MissingMetaDescriptionTests(SimpleTestCase):
    def test_triggers_on_empty_description(self):
        self.assertEqual(rules.missing_meta_description("").rule, rules.MISSING_META_DESC)

    def test_edge_whitespace_only_counts_as_missing(self):
        self.assertIsNotNone(rules.missing_meta_description("  "))

    def test_present_description_is_fine(self):
        self.assertIsNone(rules.missing_meta_description("Shop tents."))


class H1Tests(SimpleTestCase):
    def test_no_h1(self):
        self.assertEqual(rules.h1_problem(0).rule, rules.NO_H1)

    def test_multiple_h1(self):
        finding = rules.h1_problem(2)
        self.assertEqual(finding.rule, rules.MULTIPLE_H1)
        self.assertIn("2 <h1>", finding.detail)

    def test_edge_exactly_one_h1_is_fine(self):
        self.assertIsNone(rules.h1_problem(1))


class ThinContentTests(SimpleTestCase):
    def test_triggers_under_300_words(self):
        self.assertEqual(rules.thin_content(299).rule, rules.THIN_CONTENT)

    def test_edge_exactly_300_words_is_fine(self):
        self.assertIsNone(rules.thin_content(300))


class BrokenPageTests(SimpleTestCase):
    def test_triggers_on_4xx_and_5xx(self):
        self.assertEqual(rules.broken_page(404).rule, rules.BROKEN_PAGE)
        self.assertIn("HTTP 503", rules.broken_page(503).detail)

    def test_edge_400_is_broken_and_399_is_not(self):
        self.assertIsNotNone(rules.broken_page(400))
        self.assertIsNone(rules.broken_page(399))

    def test_no_response_is_broken(self):
        self.assertIn("No response", rules.broken_page(None).detail)


class EvaluateTests(SimpleTestCase):
    @staticmethod
    def rules_found(findings):
        return {finding.rule for finding in findings}

    def test_healthy_page_has_no_findings(self):
        self.assertEqual(rules.evaluate(metric(), check()), [])

    def test_combines_search_and_on_page_rules(self):
        found = rules.evaluate(metric(impressions=900, ctr=0.01, position=6), check(h1_count=0, word_count=100))
        self.assertEqual(
            self.rules_found(found), {rules.LOW_CTR, rules.STRIKING_DISTANCE, rules.NO_H1, rules.THIN_CONTENT}
        )

    def test_broken_page_skips_on_page_rules(self):
        found = rules.evaluate(metric(), check(status_code=404, title="", h1_count=0, word_count=0))
        self.assertEqual(self.rules_found(found), {rules.BROKEN_PAGE})

    def test_missing_check_runs_only_search_rules(self):
        found = rules.evaluate(metric(impressions=900, ctr=0.001), None)
        self.assertEqual(self.rules_found(found), {rules.LOW_CTR})

    def test_missing_metric_runs_only_on_page_rules(self):
        found = rules.evaluate(None, check(title=""))
        self.assertEqual(self.rules_found(found), {rules.MISSING_TITLE})


class PriorityTests(SimpleTestCase):
    def test_formula_is_weight_times_log10_impressions_plus_10(self):
        # BROKEN_PAGE has weight 3; log10(990 + 10) = 3.
        self.assertEqual(rules.priority_score(rules.BROKEN_PAGE, 990), 9.0)
        # TITLE_TOO_LONG has weight 1; log10(90 + 10) = 2.
        self.assertEqual(rules.priority_score(rules.TITLE_TOO_LONG, 90), 2.0)

    def test_zero_impressions_scores_the_weight(self):
        self.assertEqual(rules.priority_score(rules.NO_H1, 0), 2.0)
        self.assertEqual(rules.priority_score(rules.NO_H1, None), 2.0)

    def test_more_impressions_means_higher_priority(self):
        scores = [rules.priority_score(rules.THIN_CONTENT, n) for n in (0, 100, 1000, 10000, 100000)]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(len(set(scores)), len(scores))

    def test_same_traffic_ranks_worse_problems_higher(self):
        self.assertGreater(
            rules.priority_score(rules.BROKEN_PAGE, 1000), rules.priority_score(rules.TITLE_TOO_LONG, 1000)
        )

    def test_every_rule_has_a_weight_and_label(self):
        self.assertEqual(rules.RULE_WEIGHTS.keys(), rules.RULE_LABELS.keys())


class SeverityTests(SimpleTestCase):
    def test_thresholds(self):
        self.assertEqual(rules.severity_for(7), rules.HIGH)
        self.assertEqual(rules.severity_for(6.99), rules.MEDIUM)
        self.assertEqual(rules.severity_for(5), rules.MEDIUM)
        self.assertEqual(rules.severity_for(4.99), rules.LOW)

    def test_high_traffic_broken_page_is_high_and_low_traffic_is_low(self):
        self.assertEqual(rules.severity_for(rules.priority_score(rules.BROKEN_PAGE, 5000)), rules.HIGH)
        self.assertEqual(rules.severity_for(rules.priority_score(rules.BROKEN_PAGE, 0)), rules.LOW)
