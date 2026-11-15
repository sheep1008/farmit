"""LLM 호출을 모은 모듈 (REQ-NFR-011). 모든 Claude 호출은 여기를 거친다.

- 모델은 settings.LLM_MODEL (기본 claude-haiku-5-5). 설정값만 바꾸면 다른 모델로 답한다
- 시스템 프롬프트에 cache_control을 붙여 매번 같은 프롬프트를 캐싱한다 (REQ-NFR-008)
- 결과마다 입력·출력 토큰, 캐시 읽기 토큰, 응답 시간(ms)을 돌려준다. 저장은 부르는 쪽(chat_message)이 한다
- 키는 ANTHROPIC_API_KEY 환경 변수에서 SDK가 읽는다. 키·프롬프트 본문은 로그에 남기지 않는다
"""
import json
import logging
import re
import time
from dataclasses import dataclass

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

_client = None


class LlmError(Exception):
    """LLM 호출 실패. kind: rate_limit(잠시 후 재시도) | timeout | unavailable(키·네트워크·서버) | bad_request"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


@dataclass
class LlmResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str = ''


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=1)
    return _client


def _model(model=None):
    return model or settings.LLM_MODEL


# effort를 받는 모델 (thinking을 끌 수 없는 5.x 세대). 목록에 없는 모델에는 thinking 관련 값을 보내지 않는다
EFFORT_MODELS = ('claude-opus-5', 'claude-sonnet-5', 'claude-fable-5')


def _thinking_params(model):
    """빠른 답이 필요해서 생각(thinking)을 줄인다.

    Haiku 5.5는 thinking을 끌 수 있다. Opus 5.5·Sonnet 5.5는 끄면 400이라 effort를 low로 낮춘다.
    그 밖의 모델은 기본값 그대로 둔다 (지원하지 않는 값을 보내 400이 나지 않게).
    """
    if model.startswith('claude-haiku-5'):
        return {'thinking': {'type': 'disabled'}}
    if model.startswith(EFFORT_MODELS):
        return {'output_config': {'effort': 'low'}}
    return {}


def _request(system, messages, max_tokens, model):
    return {
        'model': model,
        'max_tokens': max_tokens,
        # 시스템 프롬프트는 고정 문자열만 넣는다 (날짜 등 바뀌는 값을 넣으면 캐시가 깨진다)
        'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
        'messages': messages,
        **_thinking_params(model),
    }


def _result(message, model, started):
    usage = message.usage
    text = ''.join(b.text for b in message.content if getattr(b, 'type', '') == 'text')
    result = LlmResult(
        text=text.strip(), model=model,
        input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
        cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
        cache_write_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
        latency_ms=int((time.monotonic() - started) * 1000), stop_reason=message.stop_reason or '',
    )
    logger.info('llm model=%s in=%s out=%s cache_read=%s cache_write=%s ms=%s stop=%s', model, result.input_tokens,
                result.output_tokens, result.cache_read_tokens, result.cache_write_tokens, result.latency_ms,
                result.stop_reason)
    return result


def _wrap(exc):
    """SDK 예외를 LlmError로 바꾼다. 메시지에 키·프롬프트가 들어가지 않게 종류만 남긴다."""
    if isinstance(exc, anthropic.RateLimitError):
        return LlmError('rate_limit', 'LLM 호출 한도 초과')
    if isinstance(exc, anthropic.BadRequestError):
        return LlmError('bad_request', 'LLM 요청 형식 오류')
    if isinstance(exc, anthropic.APIStatusError):
        return LlmError('unavailable', f'LLM 서버 오류 {exc.status_code}')
    if isinstance(exc, anthropic.APITimeoutError):  # APIConnectionError의 하위 클래스라 먼저 본다
        return LlmError('timeout', 'LLM 응답 시간 초과')
    if isinstance(exc, anthropic.APIConnectionError):
        return LlmError('unavailable', 'LLM 서버 접속 실패')
    return LlmError('unavailable', f'LLM 호출 실패 {type(exc).__name__}')


def complete(system, messages, max_tokens=1024, model=None):
    """한 번에 답을 받는다. 반환: LlmResult"""
    model = _model(model)
    started = time.monotonic()
    try:
        message = get_client().messages.create(**_request(system, messages, max_tokens, model))
    except anthropic.AnthropicError as exc:
        raise _wrap(exc) from None
    return _result(message, model, started)


def stream(system, messages, max_tokens=2048, model=None):
    """답을 조각으로 받는다. ('delta', 글자 조각)을 차례로 내고, 마지막에 ('done', LlmResult)를 낸다."""
    model = _model(model)
    started = time.monotonic()
    try:
        with get_client().messages.stream(**_request(system, messages, max_tokens, model)) as s:
            for text in s.text_stream:
                yield 'delta', text
            message = s.get_final_message()
    except anthropic.AnthropicError as exc:
        raise _wrap(exc) from None
    yield 'done', _result(message, model, started)


_JSON_RE = re.compile(r'\{.*\}', re.S)


def complete_json(system, user_text, max_tokens=512, model=None):
    """JSON 객체 하나를 답하게 한다. 형식이 틀리면 한 번 다시 묻는다. 반환: (dict 또는 None, [LlmResult])"""
    messages = [{'role': 'user', 'content': user_text}]
    results = []
    for _ in range(2):
        result = complete(system, messages, max_tokens=max_tokens, model=model)
        results.append(result)
        match = _JSON_RE.search(result.text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return data, results
            except json.JSONDecodeError:
                pass
        messages = messages + [
            {'role': 'assistant', 'content': result.text or '(빈 답)'},
            {'role': 'user', 'content': '설명 없이 JSON 객체 하나만 다시 출력하세요.'},
        ]
    return None, results
