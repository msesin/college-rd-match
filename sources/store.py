"""Shared helpers for writing SourceRecords and Facts.

All importers go through these functions so re-running an import updates rows
instead of duplicating them, and manual corrections are never overwritten.
"""

from django.db import transaction
from django.utils import timezone

from colleges.models import Fact, SourceRecord
from sources.parsing import to_number  # noqa: F401  (re-exported for importers)


def upsert_record(source, external_id, **fields):
    fields.setdefault("fetched_at", timezone.now())
    record, _ = SourceRecord.objects.update_or_create(
        source=source, external_id=external_id, defaults=fields
    )
    return record


@transaction.atomic
def replace_facts(record, facts):
    """Replace the parsed facts of a record, keeping any manual corrections.

    `facts` is a list of dicts with keys: section, key, label, value_num,
    value_text, method, and optionally needs_review, review_note.
    """
    manual_keys = set(
        record.facts.filter(method=Fact.METHOD_MANUAL).values_list("key", flat=True)
    )
    record.facts.exclude(method=Fact.METHOD_MANUAL).delete()
    rows = []
    seen = set()
    for f in facts:
        if f["key"] in manual_keys or f["key"] in seen:
            continue
        seen.add(f["key"])
        rows.append(
            Fact(
                college=record.college,
                record=record,
                source=record.source,
                period=f.get("period", record.period),
                section=f["section"],
                key=f["key"],
                label=f["label"][:500],
                value_num=f.get("value_num"),
                value_text=str(f.get("value_text") or "")[:10000],
                method=f["method"],
                needs_review=f.get("needs_review", False),
                review_note=f.get("review_note", "")[:300],
            )
        )
    Fact.objects.bulk_create(rows, batch_size=500)
    return len(rows)
