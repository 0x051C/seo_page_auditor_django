"""
SEO issue rules.

This module has no Django imports on purpose: every function takes plain
values and returns plain values, so it can be unit tested without a database.
"""

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
