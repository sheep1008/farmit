import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from chat.limits import remaining_today
from codes.models import Item

from .models import UserInterestItem, UserProfile
from .validators import is_valid_username

User = get_user_model()


def validate_item_ids(value):
    """관심 품목 ID 목록 검사. 가입과 내 정보 수정이 함께 쓴다.

    없는 ID가 섞여 있으면 오류, 통과하면 중복을 없앤 목록(순서 유지)을 돌려준다.
    """
    if Item.objects.filter(item_id__in=value).count() != len(set(value)):
        raise serializers.ValidationError('존재하지 않는 품목이 포함되어 있습니다.')
    return list(dict.fromkeys(value))


class SignupSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)
    sido = serializers.CharField(max_length=20)
    sigungu = serializers.CharField(max_length=20)
    interest_item_ids = serializers.ListField(
        child=serializers.IntegerField(), max_length=5, required=False, default=list)
    agree_terms = serializers.BooleanField()
    agree_privacy = serializers.BooleanField()

    def validate_username(self, value):
        if not is_valid_username(value):
            raise serializers.ValidationError('영문 소문자·숫자 4~20자로 입력해 주세요.')
        return value

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError('비밀번호는 8자 이상이어야 합니다.')
        if not re.search(r'[A-Za-z]', value) or not re.search(r'[0-9]', value):
            raise serializers.ValidationError('비밀번호는 영문자와 숫자를 모두 포함해야 합니다.')
        return value

    def validate_interest_item_ids(self, value):
        return validate_item_ids(value)

    def validate(self, attrs):
        errors = {}
        if attrs['password'] != attrs['password_confirm']:
            errors['password_confirm'] = ['비밀번호가 일치하지 않습니다.']
        if not attrs['agree_terms']:
            errors['agree_terms'] = ['이용약관에 동의해 주세요.']
        if not attrs['agree_privacy']:
            errors['agree_privacy'] = ['개인정보 처리방침에 동의해 주세요.']
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # 세 테이블 중 하나라도 실패하면 전부 되돌린다 (ACID의 원자성)
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
        )
        UserProfile.objects.create(
            user=user,
            sido=validated_data['sido'],
            sigungu=validated_data['sigungu'],
        )
        UserInterestItem.objects.bulk_create(
            [UserInterestItem(user=user, item_id=item_id) for item_id in validated_data['interest_item_ids']]
        )
        return user


class ProfileUpdateSerializer(serializers.Serializer):
    """내 정보 수정(PATCH). 보낸 필드만 바꾼다. 아이디는 바꿀 수 없다."""

    sido = serializers.CharField(max_length=20, required=False)
    sigungu = serializers.CharField(max_length=20, required=False)
    interest_item_ids = serializers.ListField(
        child=serializers.IntegerField(), max_length=5, required=False)
    transport_cost_per_km = serializers.IntegerField(min_value=0, required=False)
    storage_cost_per_week = serializers.IntegerField(min_value=0, required=False)
    # 0 이상 100 미만 (%). 소수 둘째 자리까지 저장하므로 최대 99.99
    loss_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=Decimal('99.99'), required=False)

    # UserProfile에 그대로 옮겨 담는 필드 (관심 품목은 다른 테이블이라 따로 처리)
    PROFILE_FIELDS = ('sido', 'sigungu', 'transport_cost_per_km', 'storage_cost_per_week', 'loss_rate')

    def validate_interest_item_ids(self, value):
        return validate_item_ids(value)

    def validate(self, attrs):
        if 'username' in self.initial_data:
            raise serializers.ValidationError({'username': ['아이디는 바꿀 수 없습니다.']})
        return attrs

    @transaction.atomic
    def update(self, user, validated_data):
        profile = user.userprofile
        for field in self.PROFILE_FIELDS:
            if field in validated_data:
                setattr(profile, field, validated_data[field])
        profile.save()

        # 관심 품목은 보낸 목록으로 통째로 교체한다 (빈 목록이면 모두 해제)
        if 'interest_item_ids' in validated_data:
            UserInterestItem.objects.filter(user=user).delete()
            UserInterestItem.objects.bulk_create(
                [UserInterestItem(user=user, item_id=item_id) for item_id in validated_data['interest_item_ids']]
            )
        return user


def user_data(user):
    """가입 응답 모양 (docs/api.md 2.1)."""
    profile = user.userprofile
    items = UserInterestItem.objects.filter(user=user).select_related('item')
    return {
        'id': user.id,
        'username': user.username,
        'sido': profile.sido,
        'sigungu': profile.sigungu,
        'interest_items': [{'item_id': i.item_id, 'name': i.item.name} for i in items],
    }


def me_data(user):
    """내 정보 응답 모양. 로그인·GET/PATCH /users/me가 함께 쓴다."""
    profile = user.userprofile
    data = user_data(user)
    data.update({
        'transport_cost_per_km': profile.transport_cost_per_km,
        'storage_cost_per_week': profile.storage_cost_per_week,
        'loss_rate': float(profile.loss_rate),
        'chat_remaining_today': remaining_today(user),
    })
    return data
