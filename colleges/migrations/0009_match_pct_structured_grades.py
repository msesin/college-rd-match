"""Matching engine v2: student match % instead of a chance, grades by subject instead of one transcript
tier, SAT percentiles on the college profile, and the majors graph moved into code."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("colleges", "0008_matching_engine"),
    ]

    operations = [
        migrations.DeleteModel(name="MajorNode"),
        migrations.RemoveField(model_name="student", name="transcript_tier"),
        migrations.AddField(
            model_name="student",
            name="subject_grades",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Grades by subject",
                help_text="Latest grade per subject on the school's own scale: Ukrainian 1-12, IB 1-7 (plus "
                          "'Core (TOK/EE)': 0-3), A-levels A*-E, US letter grades (AP courses start with 'AP')"),
        ),
        migrations.AlterField(
            model_name="student",
            name="academic_tier",
            field=models.CharField(
                blank=True, max_length=12, verbose_name="Olympiads & research",
                choices=[("very_strong", "Very strong"), ("strong", "Strong"), ("moderate", "Moderate")],
                help_text="Set by Gemini from the note below (run_matching); can be changed by hand"),
        ),
        migrations.AlterField(
            model_name="student",
            name="academic_note",
            field=models.TextField(blank=True, help_text="The achievements behind the level",
                                   verbose_name="Olympiads & research note"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="sat_p25",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="SAT 25th percentile",
                help_text="Enrolled first-years (CDS C9; IPEDS sections summed if no CDS)"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="sat_p75",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="SAT 75th percentile"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="sat_p30",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="SAT red-flag line (30th percentile)",
                help_text="Below this: bottom 30%. Estimated from the 25th, 50th and 75th percentiles"),
        ),
        migrations.AddField(
            model_name="collegeprofile",
            name="sat_p70",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="SAT safety line (70th percentile)",
                help_text="From this score up: top 30%. Estimated from the 25th, 50th and 75th percentiles"),
        ),
        migrations.RenameField(model_name="matchresult", old_name="likelihood", new_name="match_pct"),
        migrations.AlterField(
            model_name="matchresult",
            name="match_pct",
            field=models.FloatField(help_text="Student match %, 0-100 (not a chance of admission)",
                                    verbose_name="Match %"),
        ),
        migrations.RemoveField(model_name="matchresult", name="score"),
        migrations.AlterField(
            model_name="matchresult",
            name="rank",
            field=models.PositiveSmallIntegerField(help_text="Position in the student's list: best match first"),
        ),
    ]
