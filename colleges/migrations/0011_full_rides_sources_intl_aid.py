"""Full rides as published (text, who is counted, source link) instead of an estimate; yearly aid to
international undergraduates (CDS H6); student-triggered match runs."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("colleges", "0010_pronouns_full_rides"),
    ]

    operations = [
        migrations.RemoveField(model_name="collegeprofile", name="full_rides"),  # estimates, replaced by sourced values
        migrations.AddField(
            model_name="collegeprofile",
            name="full_rides",
            field=models.CharField(
                blank=True, default="", max_length=120, verbose_name="Full rides",
                help_text='As published: a number ("25 / year") or a share ("30% of all undergraduates"). Empty when no '
                          'reliable source gives one'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="full_rides_scope",
            field=models.CharField(blank=True, max_length=8, verbose_name="Full rides: who is counted",
                                   choices=[("intl", "International students only"),
                                            ("all", "All students (US and international)")]),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="full_rides_url",
            field=models.URLField(blank=True, max_length=500, verbose_name="Full rides: source link"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="intl_aid_total",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="International aid per year ($)",
                help_text="Institutional aid to all international undergraduates in one year (CDS H6)"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="intl_aid_students",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="International students on aid"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="intl_aid_note",
            field=models.TextField(blank=True, verbose_name="International aid note"),
        ),
        migrations.AlterField(
            model_name="matchrun",
            name="method",
            field=models.CharField(max_length=16, choices=[
                ("demo", "Demo (placeholder formula, not a prediction)"), ("algorithm", "Matching algorithm"),
                ("student", "Student's own results (run when they submit or change their list)"),
                ("import", "Imported results")]),
        ),
    ]
