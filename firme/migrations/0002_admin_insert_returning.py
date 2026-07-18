from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("firme", "0001_firme_state")]
    operations = [
        migrations.RunSQL(
            sql="""
                DROP POLICY pol_firme_select ON firme;
                CREATE POLICY pol_firme_select ON firme FOR SELECT
                    USING (
                        (cabinet_id = fn_cabinet_curent()
                         AND fn_rol_curent() IN ('admin_cabinet', 'contabil_coordonator'))
                        OR id IN (SELECT fn_firmele_utilizatorului())
                    );
            """,
            reverse_sql="""
                DROP POLICY pol_firme_select ON firme;
                CREATE POLICY pol_firme_select ON firme FOR SELECT
                    USING (id IN (SELECT fn_firmele_utilizatorului()));
            """,
        )
    ]
