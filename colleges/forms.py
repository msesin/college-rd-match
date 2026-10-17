from django import forms

from colleges.models import ColumnSetting, CollegeProfile, Program


def profile_form_class(fields):
    """A ModelForm editing only the given CollegeProfile fields."""
    text_fields = {f.name for f in CollegeProfile._meta.get_fields() if f.get_internal_type() == "TextField"}
    widgets = {name: forms.Textarea(attrs={"rows": 6}) for name in fields if name in text_fields}
    return forms.modelform_factory(CollegeProfile, fields=list(fields), widgets=widgets)


class ColumnSettingForm(forms.ModelForm):
    class Meta:
        model = ColumnSetting
        fields = ["label", "description", "visible"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class ProgramForm(forms.ModelForm):
    class Meta:
        model = Program
        fields = ["position", "name", "ranking", "rank_value", "source_url"]
        labels = {"position": "Position (1 = strongest)", "rank_value": "Rank number (optional)"}


class SubjectGradesField(forms.CharField):
    """Student.subject_grades edited as 'Subject: grade' lines."""

    widget = forms.Textarea(attrs={"rows": 8, "placeholder": "Algebra: 11\nBiology: 10\nHistory of Ukraine: 12"})

    def __init__(self, *args, **kwargs):
        kwargs.pop("encoder", None)
        kwargs.pop("decoder", None)
        kwargs["required"] = False
        kwargs.setdefault("help_text", "One subject per line, 'Subject: grade', on your school's own scale "
                                       "(Ukrainian 1-12, IB 1-7, A-levels A*-E, US letter grades; start AP courses "
                                       "with 'AP'). For IB, add 'Core (TOK/EE): 2' for the bonus points.")
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        from sources.transcript import format_grades

        return format_grades(value) if isinstance(value, dict) else value

    def to_python(self, value):
        from sources.transcript import parse_grades

        return parse_grades(value)

    def has_changed(self, initial, data):
        from sources.transcript import parse_grades

        return parse_grades(data) != (initial or {})
