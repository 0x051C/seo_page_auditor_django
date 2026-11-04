from django.contrib import admin

from .models import Issue, PageCheck, PageMetric, Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["url", "created_at"]
    search_fields = ["url"]


@admin.register(PageMetric)
class PageMetricAdmin(admin.ModelAdmin):
    list_display = ["page_url", "site", "date_start", "date_end", "clicks", "impressions", "ctr", "position"]
    list_filter = ["site", "date_end"]
    search_fields = ["page_url"]


@admin.register(PageCheck)
class PageCheckAdmin(admin.ModelAdmin):
    list_display = ["page_url", "site", "status_code", "title", "h1_count", "word_count", "has_canonical", "fetched_at"]
    list_filter = ["site", "status_code", "has_canonical"]
    search_fields = ["page_url", "title"]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["page_url", "rule", "severity", "priority", "resolved", "detected_at"]
    list_filter = ["site", "severity", "rule", "resolved"]
    search_fields = ["page_url", "detail"]
