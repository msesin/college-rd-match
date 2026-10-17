from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "UGS RD Matching: data"
admin.site.site_title = "UGS data"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("colleges.urls")),
]
