from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_over_delivery_admin_words'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='must_choose_password',
            field=models.BooleanField(default=False),
        ),
    ]
