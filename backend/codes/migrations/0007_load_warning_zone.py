# 특보구역 코드표를 넣는다. 데이터는 codes/fixtures/warning_zone.json (만드는 방법은 build_warning_zone.py 참고)
# migrate만 하면 채워지므로 따로 loaddata 할 필요가 없다. 테스트 DB에도 같이 들어간다
import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / 'fixtures' / 'warning_zone.json'


def load(apps, schema_editor):
    WarningZone = apps.get_model('codes', 'WarningZone')
    rows = json.loads(DATA.read_text(encoding='utf-8'))
    WarningZone.objects.bulk_create([WarningZone(**r) for r in rows], ignore_conflicts=True)


def unload(apps, schema_editor):
    apps.get_model('codes', 'WarningZone').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('codes', '0006_warningzone'),
    ]

    operations = [
        migrations.RunPython(load, unload),
    ]
