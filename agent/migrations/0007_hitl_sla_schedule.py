from django.db import migrations


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.update_or_create(
        name="hitl_sla_sweep",
        defaults={"func": "agent.hitl.tasks.sla_sweep", "schedule_type": "I", "minutes": 5, "repeats": -1},
    )


def remove_schedule(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name="hitl_sla_sweep").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0006_hitl_escalations"),
        ("django_q", "0018_task_success_index"),
    ]
    operations = [migrations.RunPython(create_schedule, remove_schedule)]
