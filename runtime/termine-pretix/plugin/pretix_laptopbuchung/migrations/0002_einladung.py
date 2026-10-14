from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pretix_laptopbuchung", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="teilnehmer", name="eingeladen_am",
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="teilnehmer", name="einladungen",
                            field=models.PositiveIntegerField(default=0)),
    ]
