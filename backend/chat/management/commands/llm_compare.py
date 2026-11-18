"""LLM 모델 비교: 같은 대표 질문을 여러 모델로 채팅 흐름 그대로 돌려 표로 비교한다 (REQ-NFR-011, 시험용).

사용: python manage.py llm_compare --models claude-haiku-5-5,gpt-4.1-mini [--only 1,4] [--out 폴더]
- 질문마다 실제 채팅과 같은 service.run을 부른다 (분류 LLM 1번 + 답변 LLM 1번, 검색·추천 계산 포함). 회원 한도는 쓰지 않는다
- 같은 질문 캐시는 매번 지운다 (모델끼리 답이 섞이지 않게)
- 화면: 모델별 요약(분류 정확도·평균 시간·토큰·근거 인용·오류). 파일: 질문별 답변 전문을 모델끼리 나란히 (사람이 읽고 판단)
- 실제 LLM을 부르므로 크레딧이 든다: 질문 수 × 모델 수 × 약 2번
"""
import time
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.test import override_settings
from django.utils import timezone

from chat import service
from chat.views import _recommend
from codes.models import Item
from prices.views import _today_kst
from rag.llm import LlmError

# (품목, 질문, 기대 역할). 판매는 물량을 넣어 추천 계산까지 가게 한다
QUESTIONS = [
    ('사과', '사과 500kg 언제 어디서 팔면 좋을까?', '판매'),
    ('사과', '2주 후에 어디서 파는게 좋을까?', '판매'),
    ('사과', '9월 14일 주에는 왜 이렇게 높은 가격이 형성되었어?', '시세'),
    ('사과', '요즘 사과 값이 왜 떨어졌어?', '시세'),
    ('사과', '사과 열매에 갈색 둥근 반점이 생기고 움푹 들어가요', '병해충'),
    ('사과', '잎에 검은 별 모양 무늬가 생겼어요', '병해충'),
    ('사과', '다음 주에 서리가 온다는데 사과밭은 어떻게 대비해?', '날씨재해'),
    ('사과', '사과 열매솎기는 언제 어떻게 해?', '재배'),
    ('감자', '씨감자는 언제 심어?', '재배'),
    ('감자', '감자 껍질에 딱지 같은 게 생겨요', '병해충'),
]


def run_one(question, item, today):
    """질문 1건 → {intent, answer, sources, ms, in, out, error}. 시간은 사람이 기다리는 전체 시간(검색 포함)"""
    cache.delete(service.answer_cache_key(service.crop_util.crop_name(item.name), question))
    started = time.monotonic()
    row = {'intent': None, 'answer': '', 'sources': 0, 'in': 0, 'out': 0, 'error': ''}
    try:
        for name, data in service.run(None, question, item, [], today, _recommend):
            if name == 'intent':
                row['intent'] = data['intent']
            elif name == 'final':
                row.update(answer=data['answer'], sources=len(data['sources']),
                           **{'in': data['usage'].input_tokens, 'out': data['usage'].output_tokens})
    except LlmError as e:
        row['error'] = e.kind
    except Exception as e:  # 검색 저장소 등. 한 질문 실패로 비교 전체를 멈추지 않는다
        row['error'] = type(e).__name__
    row['ms'] = int((time.monotonic() - started) * 1000)
    return row


def summarize(rows, expected):
    """한 모델의 결과 목록 → 요약 dict. 근거 인용은 LLM이 답변을 쓴 질문(토큰 출력 있음) 중 출처가 1개 이상인 비율"""
    n = len(rows)
    answered = [r for r in rows if not r['error'] and r['out']]
    return {
        'intent_ok': sum(r['intent'] == e for r, e in zip(rows, expected)),
        'n': n,
        'errors': sum(bool(r['error']) for r in rows),
        'avg_ms': int(sum(r['ms'] for r in rows) / n) if n else 0,
        'in': sum(r['in'] for r in rows),
        'out': sum(r['out'] for r in rows),
        'cited': sum(r['sources'] > 0 for r in answered),
        'answered': len(answered),
    }


class Command(BaseCommand):
    help = '같은 대표 질문으로 여러 LLM 모델을 비교한다 (실제 LLM 호출, 크레딧 사용)'

    def add_arguments(self, parser):
        parser.add_argument('--models', required=True, help='쉼표로 구분한 모델 이름')
        parser.add_argument('--only', default='', help='쉼표로 구분한 질문 번호(1부터). 비우면 전부')
        parser.add_argument('--out', default='', help='답변 전문 파일을 둘 폴더 (기본 data/llm_compare)')

    def handle(self, *args, **opts):
        models = [m.strip() for m in opts['models'].split(',') if m.strip()]
        picked = {int(x) for x in opts['only'].split(',') if x.strip()}
        questions = [q for i, q in enumerate(QUESTIONS, 1) if not picked or i in picked]
        items = {name: Item.objects.get(name=name) for name in {q[0] for q in questions}}
        today = _today_kst()
        expected = [q[2] for q in questions]
        results = {}
        for model in models:
            self.stdout.write(f'\n== {model}')
            rows = []
            with override_settings(LLM_MODEL=model):
                for i, (crop, question, want) in enumerate(questions, 1):
                    r = run_one(question, items[crop], today)
                    rows.append(r)
                    mark = 'O' if r['intent'] == want else 'X'
                    self.stdout.write(f"  {i:>2}. [{mark}] {r['intent'] or '-'}/{want} {r['ms'] / 1000:.1f}s "
                                      f"in {r['in']} out {r['out']} 출처 {r['sources']}"
                                      + (f" 오류 {r['error']}" if r['error'] else ''))
            results[model] = rows

        self.stdout.write('\n모델 | 역할 맞음 | 평균 시간 | 입력 토큰 | 출력 토큰 | 근거 인용 | 오류')
        for model, rows in results.items():
            s = summarize(rows, expected)
            self.stdout.write(f"{model} | {s['intent_ok']}/{s['n']} | {s['avg_ms'] / 1000:.1f}s | {s['in']:,} | "
                              f"{s['out']:,} | {s['cited']}/{s['answered']} | {s['errors']}")
        path = self._write(results, questions, models, opts['out'])
        self.stdout.write(self.style.SUCCESS(f'\n답변 전문: {path}'))

    def _write(self, results, questions, models, out_dir):
        # 기본은 backend/data/llm_compare (컨테이너에 마운트된 곳, data/는 .gitignore)
        out = Path(out_dir) if out_dir else settings.BASE_DIR / 'data' / 'llm_compare'
        out.mkdir(parents=True, exist_ok=True)
        now = timezone.localtime()  # 한국 시간
        path = out / f"{now:%Y%m%d-%H%M%S}.md"
        lines = [f'# LLM 비교 {now:%Y-%m-%d %H:%M}', '', f"모델: {', '.join(models)}", '']
        for i, (crop, question, want) in enumerate(questions):
            lines += [f'## {i + 1}. [{crop}] {question} (기대: {want})', '']
            for model in models:
                r = results[model][i]
                lines += [f"### {model} — {r['intent']} · {r['ms'] / 1000:.1f}s · in {r['in']} out {r['out']}"
                          + (f" · 오류 {r['error']}" if r['error'] else ''), '', r['answer'] or '(답변 없음)', '']
        path.write_text('\n'.join(lines), encoding='utf-8')
        return path
