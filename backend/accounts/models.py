from django.conf import settings
from django.db import models

from codes.models import Item


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