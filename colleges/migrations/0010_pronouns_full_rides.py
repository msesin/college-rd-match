"""Pronouns replace the student's gender (female -> she/her, male -> he/him); full rides on the college profile."""

from django.db import migrations, models


def gender_to_pronouns(apps, schema_editor):
    Student = apps.get_model("colleges", "Student")
    for old, new in (("female", "she"), ("male", "he")):
        Student.objects.filter(gender=old).update(pronouns=new)


def pronouns_to_gender(apps, schema_editor):
    Student = apps.get_model("colleges", "Student")
    for old, new in (("she", "female"), ("he", "male")):
        Student.objects.filter(pronouns=old).update(gender=new)


class Migration(migrations.Migration):

    dependencies = [
        ("colleges", "0009_match_pct_structured_grades"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="pronouns",
            field=models.CharField(
                blank=True, max_length=8, verbose_name="Pronouns",
                choices=[("she", "she/her"), ("he", "he/him"), ("they", "they/them"), ("she_they", "she/they"),
                         ("he_they", "he/they"), ("other", "Other")],
                help_text="he/him students are not matched with women's colleges"),
        ),
        migrations.RunPython(gender_to_pronouns, pronouns_to_gender),
        migrations.RemoveField(model_name="student", name="gender"),
        migrations.AddField(
            model_name="collegeprofile",
            name="full_rides",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Full rides per year (international)",
                help_text="Estimated international students per year group whose aid covers the full cost"),
        ),
        migrations.AlterField(
            model_name="matchresult",
            name="excluded",
            field=models.BooleanField(default=False, help_text="Ruled out by a hard rule (pronouns, DET, SAT)"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="full_rides_note",
            field=models.TextField(blank=True, verbose_name="Full rides note"),
        ),
    ]
