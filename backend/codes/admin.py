from django.contrib import admin

from .models import (
    Holiday,
    Item,
    Market,
    WarningZone,
    WeatherStation,
)


class CodeAdmin(admin.ModelAdmin):
    """코드 테이블 공통: 추가·수정만 허용한다.

    - 삭제 금지: 관측소·품목을 지우면 CASCADE로 수집된 날씨 일자료·관심 품목 등이 같이 지워진다.
    - 기본 키(자연키)는 수정 금지: 바꿔서 저장하면 기존 행이 아니라 새 행이 생긴다.
    """
    actions = None          # '선택 항목 삭제' 일괄 액션 제거
    pk_field = None         # 변경 화면에서 읽기 전용으로 둘 기본 키 필드 이름

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return (self.pk_field,) if obj is not None and self.pk_field else ()


@admin.register(Market)
class MarketAdmin(CodeAdmin):
    pk_field = 'market_id'
    list_display = ('market_id', 'name', 'sido', 'is_collect', 'is_reference')
    search_fields = ('market_id', 'name', 'sido')
    list_filter = ('is_collect', 'is_reference', 'sido')


@admin.register(Item)
class ItemAdmin(CodeAdmin):
    list_display = ('item_id', 'at_code', 'name', 'category', 'is_storable', 'is_forecast')
    search_fields = ('at_code', 'name')
    list_filter = ('category', 'is_storable', 'is_forecast')


@admin.register(WeatherStation)
class WeatherStationAdmin(CodeAdmin):
    pk_field = 'station_id'
    list_display = ('station_id', 'name', 'sido')
    search_fields = ('name', 'sido')
    list_filter = ('sido',)


@admin.register(Holiday)
class HolidayAdmin(CodeAdmin):
    pk_field = 'holiday_date'
    list_display = ('holiday_date', 'name')
    search_fields = ('name',)
    ordering = ('-holiday_date',)


@admin.register(WarningZone)
class WarningZoneAdmin(CodeAdmin):
    pk_field = 'region_code'
    list_display = ('region_code', 'name', 'sido', 'sigungu')
    search_fields = ('region_code', 'name', 'sigungu')
    list_filter = ('sido',)


# MarketClosure·ItemProducingArea는 복합 PK(CompositePrimaryKey)라 Django 5.2 admin에 등록할 수 없다
# (ImproperlyConfigured: composite primary key). 이 둘은 admin 없이 fixtures·SQL로 관리한다.
