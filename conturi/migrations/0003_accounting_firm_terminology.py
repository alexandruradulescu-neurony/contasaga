import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conturi", "0002_access_state"), ("firme", "0004_partener")]

    operations = [
        migrations.AlterField(
            model_name="invitatie",
            name="cabinet",
            field=models.ForeignKey(
                blank=True,
                db_column="cabinet_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invitatii_interne",
                to="firme.firmacontabilitate",
                verbose_name="firmă de contabilitate",
            ),
        ),
        migrations.AlterField(
            model_name="utilizator",
            name="rol",
            field=models.CharField(
                choices=[
                    ("superuser_platforma", "Superuser platformă"),
                    ("admin_cabinet", "Administrator firmă de contabilitate"),
                    ("contabil_coordonator", "Contabil coordonator"),
                    ("contabil", "Contabil"),
                    ("client_admin", "Administrator client"),
                    ("client_operator", "Operator client"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="invitatie",
            name="rol",
            field=models.CharField(
                choices=[
                    ("superuser_platforma", "Superuser platformă"),
                    ("admin_cabinet", "Administrator firmă de contabilitate"),
                    ("contabil_coordonator", "Contabil coordonator"),
                    ("contabil", "Contabil"),
                    ("client_admin", "Administrator client"),
                    ("client_operator", "Operator client"),
                ],
                max_length=30,
            ),
        ),
    ]
