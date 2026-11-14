import re

# 아이디 규칙: 영문 소문자·숫자 4~20자 (docs/api.md 2.1). 가입과 아이디 중복 확인이 함께 쓴다.
USERNAME_PATTERN = re.compile(r'[a-z0-9]{4,20}')


def is_valid_username(username):
    """아이디가 규칙에 맞으면 True. fullmatch라서 문자열 전체가 맞아야 한다."""
    return USERNAME_PATTERN.fullmatch(username) is not None
