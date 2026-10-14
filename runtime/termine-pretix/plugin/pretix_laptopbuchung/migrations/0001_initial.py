import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("pretixbase", "0311_fix_unshredded_invoices"),
    ]

    operations = [
        migrations.CreateModel(
            name="Teilnehmer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254)),
                ("inventarnummer", models.CharField(max_length=100)),
                ("welle", models.CharField(blank=True, max_length=100)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name="laptop_teilnehmer", to="pretixbase.event")),
                ("voucher", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                 related_name="laptop_teilnehmer", to="pretixbase.voucher")),
            ],
            options={
                "ordering": ("name",),
                "unique_together": {("event", "email"), ("event", "inventarnummer")},
            },
        ),
    ]
