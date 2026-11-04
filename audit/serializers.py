from rest_framework import serializers

from .models import Issue


class IssueSerializer(serializers.ModelSerializer):
    rule_label = serializers.CharField(source="get_rule_display", read_only=True)

    class Meta:
        model = Issue
        fields = ["id", "page_url", "rule", "rule_label", "severity", "priority", "detail", "detected_at", "resolved"]
        read_only_fields = fields
