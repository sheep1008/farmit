from django.db import models


# 시장 (erd.md 2.1)
class Market(models.Model):
    # market_id: aT 시장 코드 (PK)
    market_id = models.CharField(max_length=6, primary_key=True)
    # name: 시장 이름
    name = models.CharField(max_length=50)
    # sido: 시도
    sido = models.CharField(max_length=20)
    # lat: 위도
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    # lng: 경도
    lng = models.DecimalField(max_digits=9, decimal_places=6)

    # is_collect: 수집 대상 시장인지
    is_collect = models.BooleanField(default=False)
    # is_reference: 참고용 시장인지 (가락)
    is_reference = models.BooleanField(default=False)

    class Meta:
        db_table = 'market'


# 품목. 출처마다 코드가 달라 한 행에 모아 둔다 (erd.md 2.1)
class Item(models.Model):
    # item_id: 품목 번호 (자동 증가 PK)
    item_id = models.AutoField(primary_key=True)
    # at_code: aT 품목 코드 (중복 불가)
    at_code = models.CharField(max_length=10, unique=True)
    # name: 품목 이름
    name = models.CharField(max_length=50)
    # category: 품목 분류 (과일, 채소 등)
    category = models.CharField(max_length=20)

    # is_storable: 저장 후 출하 시점을 고를 수 있는 품목인지
    is_storable = models.BooleanField(default=False)
    # is_forecast: 가격 예측을 제공하는 품목인지 (현재는 사과만 True)
    is_forecast = models.BooleanField(default=False)
    # hs_code: 관세청 HS 코드 (수입량 알림용, 비어도 됨)
    hs_code = models.CharField(max_length=10, null=True, blank=True)
    # ncpms_crop_code: NCPMS 작물 코드 (비어도 됨)
    ncpms_crop_code = models.CharField(max_length=10, null=True, blank=True)
    # nongsaro_code: 농사로 품목 코드 (비어도 됨)
    nongsaro_code = models.CharField(max_length=10, null=True, blank=True)

    class Meta:
        db_table = 'item'


# ASOS 기상 관측소 (erd.md 2.1)
class WeatherStation(models.Model):
    # station_id: ASOS 지점 번호 (PK). 자동 증가가 아니라 기상청 번호를 그대로 쓴다
    station_id = models.IntegerField(primary_key=True)
    # name: 지점 이름
    name = models.CharField(max_length=30)
    # sido: 시도
    sido = models.CharField(max_length=20)
    # lat: 위도
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    # lng: 경도
    lng = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta:
        db_table = 'weather_station'


# 공휴일·명절 (erd.md 2.1)
class Holiday(models.Model):
    # holiday_date: 날짜 (PK)
    holiday_date = models.DateField(primary_key=True)
    # name: 이름 (설날, 추석 등)
    name = models.CharField(max_length=30)

    class Meta:
        db_table = 'holiday'


# 시장 휴장일. 직접 입력한다 (erd.md 2.1)
class MarketClosure(models.Model):
    # market: 시장 FK. 시장을 삭제하면 그 시장의 휴장일도 함께 삭제된다 (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    # closure_date: 휴장일
    closure_date = models.DateField()
    # reason: 휴장 사유. 직접 입력하는 값이라 사유를 몰라도 날짜만 넣을 수 있게 비어도 된다
    reason = models.CharField(max_length=50, null=True, blank=True)
    # pk: (market, closure_date) 복합 PK. 같은 시장의 같은 날을 두 번 등록할 수 없다
    pk = models.CompositePrimaryKey('market', 'closure_date')

    class Meta:
        db_table = 'market_closure'


# 품목별 주산지. 정산정보 원산지로 만들고 가까운 관측소를 연결한다 (erd.md 2.1)
class ItemProducingArea(models.Model):
    # item: 품목 FK. 품목을 삭제하면 주산지도 함께 삭제된다 (DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    # sido: 주산지 시도
    sido = models.CharField(max_length=20)
    # sigungu: 주산지 시군구
    sigungu = models.CharField(max_length=20)
    # station: 가장 가까운 ASOS 관측소 FK. 주산지가 쓰는 관측소는 지울 수 없게 막는다 (PROTECT)
    station = models.ForeignKey(WeatherStation, on_delete=models.PROTECT)
    # volume_share: 최근 물량 비중 (%)
    volume_share = models.DecimalField(max_digits=5, decimal_places=2)
    # pk: (item, sido, sigungu) 복합 PK. 품목마다 같은 주산지를 두 번 등록할 수 없다
    pk = models.CompositePrimaryKey('item', 'sido', 'sigungu')

    class Meta:
        db_table = 'item_producing_area'