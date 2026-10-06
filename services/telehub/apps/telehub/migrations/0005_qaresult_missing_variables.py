from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('telehub', '0004_omnichannelconfig_alter_variable_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='qaresult',
            name='missing_variables',
            field=models.JSONField(default=list),
        ),
    ]
