from django.db import models

from codes.models import WeatherStation


# ASOS 일자료 (erd.md 2.4)
class WeatherDaily(models.Model):
    # station: 관측소 FK. 관측소를 삭제하면 그 관측 자료도 함께 삭제된다 (DB 컬럼은 station_id)
    station = models.ForeignKey(WeatherStation, on_delete=models.CASCADE)
    # obs_date: 관측일
    obs_date = models.DateField()
    # avg_temp, max_temp, min_temp: 평균·최고·최저 기온 (℃). 관측값이 없는 날이 있어 비어도 된다
    avg_temp = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    max_temp = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    min_temp = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    # rain_mm: 일강수량 (mm). 관측값이 없으면 비어 있다
    rain_mm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    # humidity: 평균 습도 (%). 관측값이 없으면 비어 있다
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    # pk: (station, obs_date) 복합 PK. 같은 관측소의 같은 날 자료를 두 번 저장할 수 없다
    pk = models.CompositePrimaryKey('station', 'obs_date')

    class Meta:
        db_table = 'weather_daily'


# 기상특보 이력. 최근 6일만 제공되므로 매일 쌓는다 (erd.md 2.4)
class WeatherWarning(models.Model):
    # source_key: 발표 시각 + 지역 + 종류를 합친 값. 같은 특보가 두 번 저장되지 않게 막는다 (중복 불가)
    source_key = models.CharField(max_length=64, unique=True)
    # announced_at: 발표 시각 (UTC)
    announced_at = models.DateTimeField()
    # region_code: 특보 구역 코드
    region_code = models.CharField(max_length=20)
    # region_name: 특보 구역 이름
    region_name = models.CharField(max_length=50)
    # warning_type: 특보 종류 (폭염, 호우, 한파, 대설, 태풍 등)
    warning_type = models.CharField(max_length=20)
    # level: 단계 (주의보, 경보)
    level = models.CharField(max_length=10)
    # status: 상태 (발표, 변경, 해제)
    status = models.CharField(max_length=10)

    class Meta:
        db_table = 'weather_warning'
