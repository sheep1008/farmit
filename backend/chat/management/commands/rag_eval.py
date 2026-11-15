"""RAG 검색 품질 점검표: 대표 질문 10개의 상위 3개 근거를 보여 준다 (Y12, LLM 호출 없음)

사용: python manage.py rag_eval [--size 3]
기대 단어(expect)가 상위 3개 조각 중 하나의 제목·본문에 있으면 "맞음"으로 센다. 키워드만/벡터만/하이브리드를 비교한다.
"""
import time

from django.core.management.base import BaseCommand

from rag import embed, store

# (작물, 질문, 기대 단어) — 기대 단어는 맞는 근거라면 들어 있어야 할 말
QUESTIONS = [
    ('사과', '사과 열매에 갈색 둥근 반점이 생기고 움푹 들어가요', '탄저병'),
    ('사과', '잎에 검은 별 모양 무늬가 생겼어요', '검은별무늬병'),
    ('사과', '사과 잎이 일찍 떨어지고 갈색 무늬가 퍼져요', '갈색무늬병'),
    ('고추', '고추 열매에 물러지는 둥근 무늬가 생겨요', '탄저병'),
    ('고추', '고추 잎 뒷면에 작은 벌레가 많고 잎이 오그라들어요', '진딧물'),
    ('고추', '고추 포기가 갑자기 시들어 죽어요', '역병'),
    ('배', '배 잎에 붉은 별 모양 반점이 생겼어요', '붉은별무늬병'),
    ('딸기', '딸기 잎에 흰 가루 같은 게 생겨요', '흰가루병'),
    ('토마토', '토마토 잎 뒷면에 곰팡이가 피어요', '잎곰팡이병'),
    ('배추', '배추 뿌리에 혹이 생기고 시들어요', '뿌리혹병'),
]


def hit(results, expect):
    return any(expect in (r['title'] + r['text']) for r in results)


class Command(BaseCommand):
    help = 'RAG 검색 품질 점검표 (대표 질문 10개)'

    def add_arguments(self, parser):
        parser.add_argument('--size', type=int, default=3)

    def handle(self, *args, **opts):
        size = opts['size']
        score = {'keyword': 0, 'vector': 0, 'hybrid': 0}
        times = []
        self.stdout.write('| # | 작물 | 질문 | 기대 | 키워드 | 벡터 | 하이브리드 | 하이브리드 상위 3 |')
        self.stdout.write('|---|---|---|---|---|---|---|---|')
        for i, (crop, q, expect) in enumerate(QUESTIONS, 1):
            t = time.monotonic()
            vec = embed.embed_query(f'{crop} {q}')
            hy = store.hybrid_search([q], vec, crops=[crop], size=size)
            times.append((time.monotonic() - t) * 1000)
            kw = store.hybrid_search([q], None, crops=[crop], size=size)
            ve = store.hybrid_search([], vec, crops=[crop], size=size)
            marks = []
            for name, res in (('keyword', kw), ('vector', ve), ('hybrid', hy)):
                ok = hit(res, expect)
                score[name] += ok
                marks.append('O' if ok else 'X')
            top = ' / '.join(r['title'] for r in hy)
            self.stdout.write(f'| {i} | {crop} | {q} | {expect} | {" | ".join(marks)} | {top} |')
        n = len(QUESTIONS)
        self.stdout.write(f'\n상위 {size}개 안에 기대 근거: 키워드 {score["keyword"]}/{n}, 벡터 {score["vector"]}/{n}, '
                          f'하이브리드 {score["hybrid"]}/{n}')
        times.sort()
        self.stdout.write(f'하이브리드 검색 시간(임베딩 포함): 중앙값 {times[n // 2]:.0f}ms, 최대 {times[-1]:.0f}ms')
