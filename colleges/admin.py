from django.contrib import admin

from colleges.models import College, Fact, SourceRecord


@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    list_display = ["name", "unitid", "list_name", "state", "has_cds", "latest_cds_year"]
    list_filter = ["has_cds", "state"]
    search_fields = ["name", "list_name", "unitid"]


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ["title", "college", "source", "kind", "period", "parse_method", "parse_status", "is_primary", "fetched_at"]
    list_filter = ["source", "kind", "parse_method", "parse_status", "is_primary"]
    search_fields = ["title", "external_id", "college__name"]
    readonly_fields = ["fetched_at", "updated_at", "checksum"]
    raw_id_fields = ["college"]


@admin.register(Fact)
class FactAdmin(admin.ModelAdmin):
    list_display = ["college", "source", "section", "key", "label", "value_num", "value_text", "period", "method", "needs_review"]
    list_filter = ["source", "method", "needs_review", "section"]
    search_fields = ["key", "label", "college__name", "college__list_name"]
    list_select_related = ["college"]
    raw_id_fields = ["college", "record"]
    list_per_page = 100

    def save_model(self, request, obj, form, change):
        # A value edited by hand is a manual correction: re-running an import keeps it.
        if change and {"value_num", "value_text"} & set(form.changed_data):
            obj.method = Fact.METHOD_MANUAL
            obj.needs_review = False
            obj.review_note = f"corrected by {request.user.get_username()}"
        super().save_model(request, obj, form, change)


from colleges.models import AIAnswer, ColumnSetting, CollegeProfile, FieldHistory, Program  # noqa: E402


@admin.register(CollegeProfile)
class CollegeProfileAdmin(admin.ModelAdmin):
    list_display = ["college", "det_minimum", "det_recommended", "sat_median", "test_policy", "gpa_average",
                    "apib_preference", "olympiad_preference"]
    list_filter = ["test_policy", "apib_preference", "olympiad_preference"]
    search_fields = ["college__name"]


@admin.register(FieldHistory)
class FieldHistoryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "college", "field", "value", "source", "user"]
    list_filter = ["source", "field"]
    search_fields = ["college__name", "value", "detail"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ["college", "position", "name", "ranking", "source", "graduates", "updated_by"]
    list_filter = ["source"]
    search_fields = ["college__name", "name"]


@admin.register(ColumnSetting)
class ColumnSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "label", "position", "visible"]
    list_editable = ["label", "position", "visible"]


@admin.register(AIAnswer)
class AIAnswerAdmin(admin.ModelAdmin):
    list_display = ["created_at", "college", "question", "model", "notes_used"]
    list_filter = ["question", "model"]
    search_fields = ["college__name"]


from django import forms  # noqa: E402

from colleges.models import Student, StudentFile, StudentIdentity  # noqa: E402
from sources import crypto  # noqa: E402


class StudentAdminForm(forms.ModelForm):
    """Name and email are typed in plain text here and stored encrypted."""

    name = forms.CharField(required=False, help_text="Stored encrypted; never sent to AI models.")
    email = forms.EmailField(required=False, help_text="Stored encrypted; never sent to AI models.")

    class Meta:
        model = Student
        fields = ["cohort", "submitted_at", "pronouns", "det_score", "sat_score", "curriculum", "subject_grades", "gpa", "gpa_note", "class_top_pct", "transcript_note",
                  "major_1", "major_2", "major_3", "academic_tier", "academic_note", "self_summary",
                  "attributes", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        identity = getattr(self.instance, "identity", None) if self.instance.pk else None
        if identity:
            self.fields["name"].initial = crypto.decrypt(identity.name_encrypted)
            self.fields["email"].initial = crypto.decrypt(identity.email_encrypted)

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("name") or cleaned.get("email")) and not __import__("os").environ.get("STUDENT_DATA_KEY"):
            raise forms.ValidationError("STUDENT_DATA_KEY is not set in .env, so names cannot be stored.")
        return cleaned


class StudentFileInline(admin.TabularInline):
    model = StudentFile
    extra = 0
    fields = ["kind", "original_name", "file_path", "added_at"]
    readonly_fields = ["added_at"]


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = StudentAdminForm
    list_display = ["code", "cohort", "submitted_at", "updated_at"]  # names deliberately not listed
    actions = ["reopen_form"]

    # Deleting in the admin also removes files on disk and the login account.
    def delete_model(self, request, obj):
        from sources.students import delete_student

        delete_student(obj)

    def delete_queryset(self, request, queryset):
        from sources.students import delete_student

        for obj in queryset:
            delete_student(obj)

    @admin.action(description="Reopen the form (let the student edit and submit again)")
    def reopen_form(self, request, queryset):
        n = queryset.update(submitted_at=None)
        self.message_user(request, f"{n} form(s) reopened.")
    search_fields = ["code", "cohort"]
    readonly_fields = ["code"]
    inlines = [StudentFileInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        identity, _ = StudentIdentity.objects.get_or_create(student=obj)
        identity.name_encrypted = crypto.encrypt(form.cleaned_data.get("name") or "")
        email = crypto.normalise_email(form.cleaned_data.get("email") or "")
        identity.email_encrypted = crypto.encrypt(email)
        identity.email_hash = crypto.email_fingerprint(email) if email else ""  # lets the student sign up
        identity.save()
