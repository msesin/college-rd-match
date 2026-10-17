from django.shortcuts import redirect

# The only paths a student (non-staff user) may open.
STUDENT_PATHS = ("/portal/", "/logout/", "/static/")


class StudentAreaMiddleware:
    """Keep students inside the portal and admins out of it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            if not user.is_staff and not request.path.startswith(STUDENT_PATHS):
                return redirect("/portal/")
            if user.is_staff and request.path.startswith("/portal/"):
                return redirect("/")
        return self.get_response(request)
