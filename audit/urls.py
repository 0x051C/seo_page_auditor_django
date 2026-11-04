from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.site_list, name="site-list"),
    path("sites/<int:site_id>/report/", views.site_report, name="site-report"),
    path("api/sites/<int:site_id>/issues/", views.SiteIssueList.as_view(), name="api-site-issues"),
]
