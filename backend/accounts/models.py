from django.conf import settings
from django.db import models

from codes.models import Item, Market


# 관심 품목. 회원 : 품목 = N : M 을 잇는 중간 테이블 (erd.md 2.2)
class UserInterestItem(models.Model):
    # user: 회원 FK. 회원을 삭제하면 관심 품목도 함께 삭제된다 (DB 컬럼은 user_id)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # item: 품목 FK. 품목을 삭제하면 관심 품목도 함께 삭제된다 (DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    # pk: (user, item) 복합 PK. 같은 회원이 같은 품목을 두 번 담을 수 없다
    pk = models.CompositePrimaryKey('user', 'item')

    class Meta:
        db_table = 'user_interest_item'


# 관심 시장. 회원 : 시장 = N : M 을 잇는 중간 테이블 (erd.md 2.2). 시장 선택 상자의 ★로 넣고 뺀다
class UserInterestMarket(models.Model):
    # user: 회원 FK. 회원을 삭제하면 관심 시장도 함께 삭제된다 (DB 컬럼은 user_id)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # market: 시장 FK. 시장을 삭제하면 관심 시장도 함께 삭제된다 (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    # pk: (user, market) 복합 PK. 같은 회원이 같은 시장을 두 번 담을 수 없다
    pk = models.CompositePrimaryKey('user', 'market')

    class Meta:
        db_table = 'user_interest_market'


# 회원 프로필. auth_user와 1:1 (erd.md 2.2)
class UserProfile(models.Model):
    # user: 회원과 1:1이면서 이 테이블의 PK. 회원이 탈퇴하면 프로필도 함께 삭제된다 (DB 컬럼은 user_id)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)
    # sido: 시도. 가입할 때 필수로 받으므로 비울 수 없다
    sido = models.CharField(max_length=20, null=False)
    # sigungu: 시군구. 가입할 때 필수로 받으므로 비울 수 없다 (시군까지만 저장, REQ-NFR-006)
    sigungu = models.CharField(max_length=20, null=False)
    # lat: 시군 중심 위도. 가입 뒤 서버가 채울 수 있어 비어도 된다
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # lng: 시군 중심 경도. lat과 같은 이유로 비어도 된다
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # transport_cost_per_km: 기본 운송비 (원/km). 가입 뒤에 입력하므로 비어도 된다
    transport_cost_per_km = models.IntegerField(null=True, blank=True)
    # storage_cost_per_week: 기본 보관비 (원/주). 가입 뒤에 입력하므로 비어도 된다
    storage_cost_per_week = models.IntegerField(null=True, blank=True)
    # loss_rate: 기본 감모율 (%). 입력하지 않으면 0
    loss_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        db_table = 'user_profile'

# 판매 기록. 회원이 직접 입력한 판매 결과 (erd.md 3절, REQ-SAL-001~002)
#   평균 대비 %는 저장하지 않고 조회할 때 settle_price와 맞춰 계산한다
class SaleRecord(models.Model):
    # user: 회원 FK. 회원을 삭제하면 판매 기록도 함께 삭제된다 (DB 컬럼은 user_id)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # sale_date: 판매한 날
    sale_date = models.DateField()
    # market: 시장 FK. 판매 기록이 있는 시장은 지울 수 없게 막는다 (PROTECT, DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # item: 품목 FK. 판매 기록이 있는 품목은 지울 수 없게 막는다 (PROTECT, DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # grade: 등급. 모르면 전 등급 평균과 비교하는 'ALL' (settle_price.grade와 같은 값)
    grade = models.CharField(max_length=10, default='ALL')
    # volume_kg: 판매 물량 (kg)
    volume_kg = models.DecimalField(max_digits=12, decimal_places=1)
    # amount_won: 받은 금액 (원, 총액)
    amount_won = models.BigIntegerField()
    # created_at: 기록한 시각 (UTC)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sale_record'
        # 내 기록을 날짜순으로 보는 목록용
        indexes = [models.Index(fields=['user', 'sale_date'], name='idx_sale_user_date')]
