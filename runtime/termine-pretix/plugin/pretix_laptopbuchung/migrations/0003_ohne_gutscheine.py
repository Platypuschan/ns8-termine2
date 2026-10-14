import secrets

import django.db.models.deletion

import pretix_laptopbuchung.models
from django.db import migrations, models


def tokens_vergeben(apps, schema_editor):
    Teilnehmer = apps.get_model("pretix_laptopbuchung", "Teilnehmer")
    for tn in Teilnehmer.objects.all():
        tn.token = secrets.token_urlsafe(16)
        tn.save(update_fields=["token"])


class Migration(migrations.Migration):
    dependencies = [
        ("pretix_laptopbuchung", "0002_einladung"),
        ("pretixbase", "0311_fix_unshredded_invoices"),
    ]

    operations = [
        migrations.AddField(model_name="teilnehmer", name="token", field=models.CharField(max_length=64, null=True)),
        migrations.RunPython(tokens_vergeben, migrations.RunPython.noop),
        migrations.AlterField(model_name="teilnehmer", name="token",
                              field=models.CharField(max_length=64, unique=True,
                                                     default=pretix_laptopbuchung.models.neues_token)),
        migrations.RemoveField(model_name="teilnehmer", name="voucher"),
        migrations.CreateModel(
            name="Buchung",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("erstellt", models.DateTimeField(auto_now_add=True)),
                ("position", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                  related_name="laptop_buchung", to="pretixbase.orderposition")),
                ("teilnehmer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                 related_name="buchungen", to="pretix_laptopbuchung.teilnehmer")),
            ],
        ),
    ]
