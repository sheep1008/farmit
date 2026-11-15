# ASOS 관측소 목록을 넣는다. 데이터는 codes/fixtures/weather_station.json (만드는 방법은 build_weather_station.py 참고)
# migrate만 하면 채워지므로 따로 loaddata 할 필요가 없다. 테스트 DB에도 같이 들어간다
import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / 'fixtures' / 'weather_station.json'


def load(apps, schema_editor):
    WeatherStation = apps.get_model('codes', 'WeatherStation')
    rows = json.loads(DATA.read_text(encoding='utf-8'))
    WeatherStation.objects.bulk_create([WeatherStation(**r) for r in rows], ignore_conflicts=True)


def unload(apps, schema_editor):
    apps.get_model('codes', 'WeatherStation').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('codes', '0007_load_warning_zone'),
    ]

    operations = [
        migrations.RunPython(load, unload),
    ]
