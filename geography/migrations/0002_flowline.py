import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('geography', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Flowline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=200)),
                ('feature_type', models.CharField(blank=True, max_length=100)),
                ('length_km', models.FloatField(blank=True, null=True)),
                ('stream_order', models.IntegerField(blank=True, null=True)),
                ('source_id', models.CharField(blank=True, max_length=20)),
                ('geometry', django.contrib.gis.db.models.fields.MultiLineStringField(srid=4326)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('boundary', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='flowlines', to='geography.boundary')),
            ],
        ),
    ]
