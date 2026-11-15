from django.contrib import admin

from .models import (
    Holiday,
    Item,
    ItemProducingArea,
    Market,
    MarketClosure,
    WarningZone,
    WeatherStation,
)


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ('market_id', 'name', 'sido', 'is_collect', 'is_reference')
    search_fields = ('market_id', 'name', 'sido')
    list_filter = ('is_collect', 'is_reference', 'sido')


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'at_code', 'name', 'category', 'is_storable', 'is_forecast')
    search_fields = ('at_code', 'name')
    list_filter = ('category', 'is_storable', 'is_forecast')


@admin.register(WeatherStation)
class WeatherStationAdmin(admin.ModelAdmin):
    list_display = ('station_id', 'name', 'sido')
    search_fields = ('name', 'sido')
    list_filter = ('sido',)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('holiday_date', 'name')
    search_fields = ('name',)
    ordering = ('-holiday_date',)


@admin.register(WarningZone)
class WarningZoneAdmin(admin.ModelAdmin):
    list_display = ('region_code', 'name', 'sido', 'sigungu')
    search_fields = ('region_code', 'name', 'sigungu')
    list_filter = ('sido',)


class ReadOnlyCompositeAdmin(admin.ModelAdmin):
    # 복합 PK(CompositePrimaryKey)는 Django 5.2 admin이 변경·삭제 화면 주소를 못 만들어 조회만 허용한다
    actions = None
    list_display_links = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarketClosure)
class MarketClosureAdmin(ReadOnlyCompositeAdmin):
    list_display = ('market', 'closure_date', 'reason')
    search_fields = ('market__name', 'reason')
    list_filter = ('market',)
    list_select_related = ('market',)
    ordering = ('-closure_date', 'market')


@admin.register(ItemProducingArea)
class ItemProducingAreaAdmin(ReadOnlyCompositeAdmin):
    list_display = ('item', 'sido', 'sigungu', 'station', 'volume_share')
    search_fields = ('item__name', 'sido', 'sigungu')
    list_filter = ('sido',)
    list_select_related = ('item', 'station')
    ordering = ('item', '-volume_share')
