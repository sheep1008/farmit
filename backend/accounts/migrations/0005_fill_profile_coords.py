from django.db import migrations

from codes.regions import sigungu_coords


def fill_coords(apps, schema_editor):
    """좌표가 빈 회원의 lat·lng를 시군구 중심 좌표로 채운다.

    가입·내 정보 수정이 좌표를 채우지 않던 때 가입한 회원용. 이미 좌표가 있는 회원은 건드리지 않고,
    목록에 없는 시도·시군구(표기가 다른 값)는 빈 채로 둔다. 다시 실행해도 결과가 같다.
    """
    UserProfile = apps.get_model('accounts', 'UserProfile')
    for profile in UserProfile.objects.filter(lat__isnull=True):
        lat, lng = sigungu_coords(profile.sido, profile.sigungu)
        if lat is not None:
            profile.lat, profile.lng = lat, lng
            profile.save(update_fields=['lat', 'lng'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userinterestmarket'),
    ]

    operations = [
        migrations.RunPython(fill_coords, migrations.RunPython.noop),
    ]
