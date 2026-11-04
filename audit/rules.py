"""
SEO issue rules.

This module has no Django imports on purpose: every function takes plain
values and returns plain values, with no database or network access. The
same input always gives the same output, so each rule can be unit tested
with a single line of setup.
"""

import math
from dataclasses import dataclass

# Rule codes, stored in Issue.rule.
LOW_CTR = "LOW_CTR"
STRIKING_DISTANCE = "STRIKING_DISTANCE"
MISSING_TITLE = "MISSING_TITLE"
TITLE_TOO_LONG = "TITLE_TOO_LONG"
MISSING_META_DESC = "MISSING_META_DESC"
NO_H1 = "NO_H1"
MULTIPLE_H1 = "MULTIPLE_H1"
THIN_CONTENT = "THIN_CONTENT"
BROKEN_PAGE = "BROKEN_PAGE"

RULE_LABELS = {
    LOW_CTR: "Low CTR",
    STRIKING_DISTANCE: "Striking distance",
    MISSING_TITLE: "Missing title",
    TITLE_TOO_LONG: "Title too long",
    MISSING_META_DESC: "Missing meta description",
    NO_H1: "No H1",
    MULTIPLE_H1: "Multiple H1s",
    THIN_CONTENT: "Thin content",
    BROKEN_PAGE: "Broken page",
}

# Severity levels, stored in Issue.severity.
LOW = "low"
MEDIUM = "medium"
HIGH = "high"

SEVERITY_LABELS = {
    LOW: "Low",
    MEDIUM: "Medium",
    HIGH: "High",
}

# Thresholds from the spec.
LOW_CTR_MIN_IMPRESSIONS = 500
LOW_CTR_MAX_CTR = 0.015  # 1.5%
STRIKING_MIN_POSITION = 4
STRIKING_MAX_POSITION = 10
STRIKING_MIN_IMPRESSIONS = 200
TITLE_MAX_LENGTH = 60
THIN_CONTENT_MIN_WORDS = 300

# How bad each problem is on its own, before traffic is considered.
# 3 = the page is unusable or invisible in results, 2 = losing clicks or
# rankings, 1 = cosmetic.
RULE_WEIGHTS = {
    BROKEN_PAGE: 3,
    MISSING_TITLE: 3,
    LOW_CTR: 2,
    STRIKING_DISTANCE: 2,
    MISSING_META_DESC: 2,
    NO_H1: 2,
    THIN_CONTENT: 2,
    TITLE_TOO_LONG: 1,
    MULTIPLE_H1: 1,
}

# Priority score cut-offs for severity. For a weight-2 rule, 7 means about
# 3,150 impressions and 5 about 300.
HIGH_PRIORITY = 7
MEDIUM_PRIORITY = 5


@dataclass(frozen=True)
class Finding:
    rule: str
    detail: str


# --- Search Console rules -------------------------------------------------


def low_ctr(impressions, ctr):
    """Plenty of people see the page in results but few click."""
    if impressions >= LOW_CTR_MIN_IMPRESSIONS and ctr < LOW_CTR_MAX_CTR:
        return Finding(
            LOW_CTR,
            f"CTR is {ctr:.2%} on {impressions:,} impressions (target: at least {LOW_CTR_MAX_CTR:.1%}). "
            "Rewrite the title and meta description to earn the click.",
        )
    return None


def striking_distance(impressions, position):
    """Ranks just below the top results, where a small push pays off most."""
    if STRIKING_MIN_POSITION <= position <= STRIKING_MAX_POSITION and impressions >= STRIKING_MIN_IMPRESSIONS:
        return Finding(
            STRIKING_DISTANCE,
            f"Average position {position:.1f} with {impressions:,} impressions. "
            "Close to the top 3: improve the content and add internal links.",
        )
    return None


# --- On-page rules ----------------------------------------------------------


def missing_title(title):
    if not title.strip():
        return Finding(MISSING_TITLE, "The page has no <title>.")
    return None


def title_too_long(title):
    length = len(title.strip())
    if length > TITLE_MAX_LENGTH:
        return Finding(
            TITLE_TOO_LONG,
            f"Title is {length} characters (max {TITLE_MAX_LENGTH}); search results will cut it off.",
        )
    return None


def missing_meta_description(meta_description):
    if not meta_description.strip():
        return Finding(MISSING_META_DESC, "No meta description, so Google picks the snippet itself.")
    return None


def h1_problem(h1_count):
    """Exactly one H1 is expected. Returns NO_H1, MULTIPLE_H1, or None."""
    if h1_count == 0:
        return Finding(NO_H1, "The page has no <h1> heading.")
    if h1_count > 1:
        return Finding(MULTIPLE_H1, f"The page has {h1_count} <h1> headings; use one main heading.")
    return None


def thin_content(word_count):
    if word_count < THIN_CONTENT_MIN_WORDS:
        return Finding(THIN_CONTENT, f"Only {word_count} words (minimum {THIN_CONTENT_MIN_WORDS}).")
    return None


def broken_page(status_code):
    """status_code None means the request got no response at all."""
    if status_code is None:
        return Finding(BROKEN_PAGE, "No response (timeout or connection error).")
    if status_code >= 400:
        return Finding(BROKEN_PAGE, f"The page returned HTTP {status_code}.")
    return None


# --- Putting it together ------------------------------------------------------


def evaluate(metric=None, check=None):
    """
    Run every rule for one page and return the list of Findings.

    `metric` is anything with impressions, ctr and position (a PageMetric).
    `check` is anything with status_code, title, meta_description, h1_count
    and word_count (a PageCheck). Either may be None if that data is missing.
    On-page rules are skipped for broken pages, since an error page's title
    and word count say nothing about the real page.
    """
    findings = []
    if metric is not None:
        findings.append(low_ctr(metric.impressions, metric.ctr))
        findings.append(striking_distance(metric.impressions, metric.position))
    if check is not None:
        broken = broken_page(check.status_code)
        if broken:
            findings.append(broken)
        else:
            findings.append(missing_title(check.title))
            findings.append(title_too_long(check.title))
            findings.append(missing_meta_description(check.meta_description))
            findings.append(h1_problem(check.h1_count))
            findings.append(thin_content(check.word_count))
    return [finding for finding in findings if finding is not None]


def priority_score(rule, impressions):
    """
    priority = rule weight x log10(impressions + 10)

    log10 because impressions span orders of magnitude: a page with 10,000
    impressions should rank above one with 100, but not 100 times higher.
    The +10 means a page with no impressions still scores its weight x 1.
    """
    traffic = math.log10(max(impressions or 0, 0) + 10)
    return round(RULE_WEIGHTS[rule] * traffic, 2)


def severity_for(score):
    if score >= HIGH_PRIORITY:
        return HIGH
    if score >= MEDIUM_PRIORITY:
        return MEDIUM
    return LOW
