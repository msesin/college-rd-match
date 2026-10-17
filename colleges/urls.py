from django.urls import path

from django.contrib.auth import views as auth_views

from colleges import views, views_portal

urlpatterns = [
    # sign-in for everyone; students sign up with their email
    path("login/", auth_views.LoginView.as_view(template_name="colleges/portal/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views_portal.register, name="register"),
    path("register/<str:token>/", views_portal.register_confirm, name="register_confirm"),
    # student portal
    path("portal/", views_portal.portal, name="portal"),
    path("portal/matches/", views_portal.portal_matches, name="portal_matches"),
    path("portal/matches/state/", views_portal.portal_matches_state, name="portal_matches_state"),
    path("portal/list/", views_portal.portal_list_change, name="portal_list_change"),
    path("portal/files/<int:pk>/", views_portal.portal_file, name="portal_file"),
    path("portal/files/<int:pk>/delete/", views_portal.portal_file_delete, name="portal_file_delete"),
    # admin: match results
    path("match/", views.match_page, name="match"),
    path("match/majors/", views.majors_graph, name="majors_graph"),
    path("weights/", views.college_weights, name="college_weights"),
    path("ugs-results/", views.ugs_results, name="ugs_results"),
    path("", views.dashboard, name="dashboard"),
    path("cell/<int:unitid>/<slug:key>/", views.cell_edit, name="cell_edit"),
    path("column/<slug:key>/", views.column_edit, name="column_edit"),
    path("columns/order/", views.column_order, name="column_order"),
    path("programs/", views.programs_grid, name="programs"),
    path("programs/list/", views.programs_page, name="programs_list"),
    path("programs/<int:pk>/edit/", views.program_edit, name="program_edit"),
    path("programs/<int:pk>/delete/", views.program_delete, name="program_delete"),
    path("programs/add/<int:unitid>/", views.program_add, name="program_add"),
    path("college/<int:unitid>/", views.college_detail, name="college_detail"),
    path("students/", views.students_page, name="students"),
    path("students/add/", views.student_name_edit, name="student_add"),
    path("students/<str:code>/", views.student_detail, name="student_detail"),
    path("students/<str:code>/delete/", views.student_delete, name="student_delete"),
    path("students/<str:code>/name/", views.student_name_edit, name="student_name_edit"),
    path("students/<str:code>/cell/<slug:key>/", views.student_cell_edit, name="student_cell_edit"),
    path("students/<str:code>/file/<int:pk>/", views.student_file, name="student_file"),
    path("record/<int:pk>/", views.record_detail, name="record_detail"),
    path("record/<int:pk>/file/", views.record_file, name="record_file"),
]
