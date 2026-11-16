"""채팅 답변 흐름 (Y13, REQ-CHT-001~005).

질문 1건: 다른 품목·범위 밖 규칙 검사(LLM 없음) → 역할 판단(LLM 1번) → 범위 밖이면 안내(답변 LLM 없음)
→ 판매: 품목·물량을 되묻거나 판매 추천 계산 결과를 설명 / 그 밖: RAG 검색 → 답변 스트리밍
→ 줄마다 약제 사용량 치환·근거 목록에 없는 번호 제거 → 인용된 근거만 출처로 → 면책 문구.

run()은 (이벤트 이름, dict)를 차례로 내는 제너레이터다. 뷰가 SSE로 바꿔 보낸다. DB 저장은 뷰가 한다.
"""
import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.cache import cache

from chat import prompts as P
from codes.models import Item
from rag import crops as crop_util
from rag import guide_links as guide
from rag import llm, retrieve
from rag.dose_filter import SENT_SPLIT_RE, is_dose, mask_sentence

logger = logging.getLogger(__name__)

CITE_RE = re.compile(r'\[근거\s*(\d+(?:\s*[,·]\s*\d+)*)\]')
HISTORY_TURNS = 4            # 역할 판단에 넣는 이전 메시지 수
EVIDENCE_SIZE = 6
MAX_VOLUME_KG = 1_000_000_000
ANSWER_CACHE_SECONDS = 60 * 60 * 24
SALES_SOURCE = {'n': 1, 'title': '팜잇 판매 추천 계산', 'source_label': '팜잇 (aT 정산가격·주간 가격 예측)',
                'url': '', 'source_type': 'recommendation'}

# LLM 없이 범위 밖으로 보는 말 (REQ-CHT-004). 농업 질문과 겹치지 않는 주제만 둔다
OUT_OF_SCOPE_WORDS = ['보조금', '지원금', '지원사업', '대출', '융자', '보험금', '주식', '코인', '비트코인', '로또',
                      '레시피', '요리법', '맛집', '연애', '정치', '선거', '게임', '영화']
# '날씨 예보'·'세금'은 넣지 않는다: "날씨 예보에 서리가 온다는데"(날씨재해), "세금 떼면 얼마 남아요"(판매) 같은 질문을 막는다


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    calls: list = field(default_factory=list)

    def add(self, result):
        # 입력 토큰은 캐시에서 읽거나 쓴 것까지 합친다 (프롬프트 전체 크기. 비용은 calls의 cache_read로 따로 볼 수 있다)
        self.input_tokens += result.input_tokens + result.cache_read_tokens + result.cache_write_tokens
        self.output_tokens += result.output_tokens
        self.latency_ms += result.latency_ms
        self.calls.append({'model': result.model, 'in': result.input_tokens, 'out': result.output_tokens,
                           'cache_read': result.cache_read_tokens, 'ms': result.latency_ms})


def known_crop_names():
    return crop_util.crop_names_for_items(Item.objects.all())


def rule_check(question, crop, known):
    """LLM 없이 바로 안내할 질문이면 안내 문구, 아니면 None."""
    found = crop_util.find_crops(question, known)
    if crop and found and crop not in found:
        return P.OTHER_CROP.format(crop=crop, other=found[0], other_ro=P.josa(found[0], '으로', '로'))
    if any(w in question for w in OUT_OF_SCOPE_WORDS):
        return P.OUT_OF_SCOPE
    return None


def history_text(history):
    lines = []
    for m in history[-HISTORY_TURNS:]:
        who = '사용자' if m['role'] == 'user' else '상담'
        lines.append(f"{who}: {m['content'][:300]}")
    return '\n'.join(lines) or '(없음)'


def classify(question, crop, history, today, usage):
    data, results = llm.complete_json(P.CLASSIFY_SYSTEM, P.CLASSIFY_USER.format(
        today=today.isoformat(), crop=crop or '(선택 안 함)', history=history_text(history), question=question),
        max_tokens=300)
    for r in results:
        usage.add(r)
    data = data or {}
    intent = data.get('intent') if data.get('intent') in P.INTENTS else '재배'
    queries = [q for q in (data.get('queries') or []) if isinstance(q, str)][:4]
    try:
        volume = float(data['volume_kg']) if data.get('volume_kg') is not None else None
    except (TypeError, ValueError):
        volume = None
    # NaN·무한대·터무니없는 값(LLM이 json으로 줄 수 있다)은 물량이 없는 것으로 보고 다시 묻는다
    if volume is not None and not (math.isfinite(volume) and 0 < volume <= MAX_VOLUME_KG):
        volume = None
    desired = None
    try:
        if data.get('desired_date'):
            desired = date.fromisoformat(str(data['desired_date']))
    except ValueError:
        pass
    return {'intent': intent, 'crop': data.get('crop') if isinstance(data.get('crop'), str) else None,
            'queries': queries, 'volume_kg': volume, 'desired_date': desired}


class LineFilter:
    """스트리밍 글자를 줄 단위로 모아 안전 처리한 뒤 내보낸다.

    - 약제 사용량 → "[사용량: 등록 기준 확인]" (REQ-CHT-005). 처리 전 숫자가 화면에 잠깐도 나오지 않게 줄이 끝나야 내보낸다
    - [근거 n]에서 근거 목록에 없는 번호를 지운다 (REQ-CHT-003)
    """

    def __init__(self, valid_numbers):
        self.valid = set(valid_numbers)
        self.buf = ''
        self.parent = ''
        self.out = []

    def _fix_cites(self, line):
        def rep(m):
            nums = [int(n) for n in re.split(r'\s*[,·]\s*', m.group(1))]
            keep = [n for n in dict.fromkeys(nums) if n in self.valid]
            return ''.join(f'[근거 {n}]' for n in keep)
        return CITE_RE.sub(rep, line)

    def _line(self, line):
        # 문장마다 앞 문장(같은 줄의 앞 문장, 없으면 앞 줄)을 문맥으로 본다.
        # "만코제브 수화제를 쓰세요. 500배로 타서 뿌립니다."의 둘째 문장도 약제 문맥으로 잡으려고
        parts = SENT_SPLIT_RE.split(line)
        out = []
        for i, part in enumerate(parts):
            if i % 2 == 0 and part.strip():
                masked = is_dose(part, self.parent)
                if masked:
                    part = mask_sentence(part)
                # 치환한 문장은 약제 문맥이 이어지는 것으로 본다 ("500배로 타서 뿌립니다." 다음 "물 20L당 20g")
                self.parent = '약제 ' + part if masked else part
            out.append(part)
        line = self._fix_cites(''.join(out))
        self.out.append(line)
        return line

    def feed(self, text):
        self.buf += text
        lines = []
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            lines.append(self._line(line) + '\n')
        return ''.join(lines)

    def flush(self):
        if not self.buf:
            return ''
        line, self.buf = self.buf, ''
        return self._line(line)

    def text(self):
        return '\n'.join(self.out).strip()


def cited(answer, evidence):
    nums = []
    for m in CITE_RE.finditer(answer):
        for n in re.split(r'\s*[,·]\s*', m.group(1)):
            if int(n) not in nums:
                nums.append(int(n))
    by_n = {e['n']: e for e in evidence}
    return [{'n': n, 'title': by_n[n]['title'], 'source_label': by_n[n]['source_label'],
             'url': by_n[n].get('url', ''), 'source_type': by_n[n].get('source_type', '')}
            for n in sorted(nums) if n in by_n]


def answer_cache_key(crop, question):
    norm = re.sub(r'\s+', ' ', question).strip()
    return 'chat:answer:' + hashlib.sha256(f'{crop}|{norm}'.encode()).hexdigest()


def _stream_answer(system, user_content, evidence, usage, max_tokens=1500):
    """LLM 답변을 줄 단위로 안전 처리하며 delta 이벤트로 낸다. 반환은 마지막에 ('answer', 최종 본문)."""
    f = LineFilter([e['n'] for e in evidence])
    for kind, value in llm.stream(system, [{'role': 'user', 'content': user_content}], max_tokens=max_tokens):
        if kind == 'delta':
            out = f.feed(value)
            if out:
                yield 'delta', {'text': out}
        else:
            usage.add(value)
    tail = f.flush()
    if tail:
        yield 'delta', {'text': tail}
    yield 'answer', {'text': f.text()}


def _final(text, evidence, disclaimer=True):
    body = text.strip()
    if disclaimer:
        body = f'{body}\n\n{P.DISCLAIMER}'
    return body, cited(text, evidence)


def _sales_result_text(data, meta):
    """추천 계산 응답 → LLM에 줄 짧은 표 (상위 5개). 숫자는 계산 결과 그대로."""
    if not data['forecast_available']:
        rows = data.get('market_comparison') or []
        lines = [f"예측 대상이 아닌 품목이라 최근 정산일({meta.get('date')}) 시장별 평균 가격만 있습니다."]
        lines += [f"- {r.get('market_name')}: {r.get('avg_price')}원/kg" for r in rows[:5]]
        return '\n'.join(lines)
    lines = [f"물량 {meta['volume_kg']}kg, 예측 기준 주 {meta['base_week']}, "
             f"운송비 반영 {'예' if meta['costs']['transport_applied'] else '아니오(내 위치 미입력)'}"]
    rows = data['results'][:5]
    wanted = next((r for r in data['results'] if r.get('is_desired')), None)
    if wanted and wanted not in rows:
        rows = rows + [wanted]  # 원하는 주의 가장 좋은 행은 순위가 낮아도 넣는다
    for r in rows:
        extra = []
        if r.get('is_desired'):
            extra.append('농가가 원한 판매 주')
        if r['is_closed']:
            extra.append(f"휴장일 {', '.join(r['closed_dates'])}")
        if r['holiday_notice']:
            extra.append(r['holiday_notice'])
        lines.append(
            f"{r['rank']}순위: {r['market_name']}, {r['target_week']} 주, 예측가 {r['pred_price']}원/kg "
            f"(80% 범위 {r['lower80']}~{r['upper80']}), 손에 남는 돈 {r['net_won']:,}원 "
            f"(범위 {r['net_low_won']:,}~{r['net_high_won']:,}원), 운송비 {r['transport_won']:,}원, "
            f"보관비 {r['storage_won']:,}원" + (f" / 주의: {'; '.join(extra)}" if extra else ''))
    return '\n'.join(lines)


def find_item(crop):
    """작물 이름 → 가격 품목(Item). 이름이 같은 품목, 없으면 작물 이름이 같은 첫 품목."""
    if not crop:
        return None
    item = Item.objects.filter(name=crop).first()
    if item:
        return item
    for it in Item.objects.order_by('item_id'):
        if crop_util.crop_name(it.name) == crop:
            return it
    return None


def run(user, question, item, history, today, recommend):
    """질문 1건 처리. 이벤트: status, intent, delta, sources, final(본문·출처·역할·사용량·캐시 여부)

    recommend(user, item, volume_kg, desired_date) → (status, data, meta): prices의 판매 추천 계산.
    """
    usage = Usage()
    crop = crop_util.crop_name(item.name) if item else None
    known = known_crop_names()

    def done(intent, text, sources, disclaimer=True, evidence=None, cached=False, guide_links=None):
        body, cites = _final(text, evidence or [], disclaimer)
        data = {'intent': intent, 'answer': body, 'sources': sources if sources is not None else cites,
                'usage': usage, 'cached': cached}
        if guide_links is not None:
            data['guide_links'] = guide_links
        return 'final', data

    # 1) 규칙: 다른 품목·범위 밖 (LLM 없음, REQ-CHT-004)
    notice = rule_check(question, crop, known)
    if notice:
        yield 'intent', {'intent': '범위밖'}
        yield 'delta', {'text': notice}
        yield done('범위밖', notice, [], disclaimer=False)
        return

    # 2) 같은 질문 캐시 (REQ-NFR-002). 대화 첫 질문만 (앞 대화에 따라 뜻이 바뀌는 질문을 피하려고)
    key = answer_cache_key(crop, question)
    if not history:
        hit = cache.get(key)
        if hit:
            yield 'intent', {'intent': hit['intent']}
            yield 'delta', {'text': hit['answer']}
            yield 'final', {**hit, 'usage': usage, 'cached': True}
            return

    # 3) 역할 판단 (LLM 1번)
    yield 'status', {'step': 'classify', 'message': '질문을 이해하는 중'}
    c = classify(question, crop, history, today, usage)
    intent = c['intent']
    yield 'intent', {'intent': intent}
    if intent == '범위밖':
        yield 'delta', {'text': P.OUT_OF_SCOPE}
        yield done('범위밖', P.OUT_OF_SCOPE, [], disclaimer=False)
        return
    q_crop = crop or (c['crop'] if c['crop'] in known else None)
    if crop and c['crop'] and c['crop'] != crop and c['crop'] in known:
        msg = P.OTHER_CROP.format(crop=crop, other=c['crop'], other_ro=P.josa(c['crop'], '으로', '로'))
        yield 'delta', {'text': msg}
        yield done(intent, msg, [], disclaimer=False)
        return

    # 4) 판매 상담 (REQ-CHT-002)
    if intent == '판매':
        sale_item = item or find_item(q_crop or c['crop'])
        if sale_item is None:
            msg = P.UNKNOWN_CROP.format(crop_eun=P.josa(c['crop'], '은', '는')) if c['crop'] else P.ASK_CROP
            yield 'delta', {'text': msg}
            yield done(intent, msg, [], disclaimer=False)
            return
        sale_crop = sale_item.name
        if c['volume_kg'] is None:
            msg = P.ASK_VOLUME.format(crop_eul=P.josa(sale_crop, '을', '를'))
            yield 'delta', {'text': msg}
            yield done(intent, msg, [], disclaimer=False)
            return
        yield 'status', {'step': 'recommend', 'message': '시장별 손에 남는 돈을 계산하는 중'}
        status, data, meta = recommend(user, sale_item, c['volume_kg'], c['desired_date'])
        if status != 200:
            msg = P.NO_FORECAST_YET.format(crop=sale_crop)
            yield 'delta', {'text': msg}
            yield done(intent, msg, [], disclaimer=False)
            return
        yield 'status', {'step': 'answer', 'message': '추천 결과를 설명하는 중'}
        evidence = [SALES_SOURCE]
        text = ''
        for kind, value in _stream_answer(P.SALES_SYSTEM, P.SALES_USER.format(
                crop=sale_crop, question=question, result=_sales_result_text(data, meta)), evidence, usage, 1000):
            if kind == 'answer':
                text = value['text']
            else:
                yield kind, value
        result = done(intent, text, None, evidence=evidence)
        result[1]['recommendation'] = {'item_id': sale_item.item_id, 'volume_kg': c['volume_kg'],
                                       'top': (data.get('results') or [])[:3]}
        yield result
        return

    # 5) RAG 답변 (병해충·날씨재해·재배)
    yield 'status', {'step': 'search', 'message': '농촌진흥청 자료를 찾는 중'}
    evidence = retrieve.search(question, crop=q_crop, queries=c['queries'], size=EVIDENCE_SIZE)
    if not evidence:
        msg = f'{P.NOT_FOUND}. 다른 표현으로 물어보시거나 가까운 농업기술센터에 문의해 주세요.'
        yield 'delta', {'text': msg}
        yield done(intent, msg, [])
        return
    yield 'status', {'step': 'answer', 'message': f'근거 {len(evidence)}건으로 답변을 쓰는 중'}
    text = ''
    for kind, value in _stream_answer(P.ANSWER_SYSTEM, P.ANSWER_USER.format(
            crop=q_crop or '(선택 안 함)', role=P.INTENT_LABELS[intent], role_format=P.ROLE_FORMAT[intent],
            question=question, evidence=retrieve.format_evidence(evidence)), evidence, usage):
        if kind == 'answer':
            text = value['text']
        else:
            yield kind, value
    # 원문 링크 (REQ-CHT-007): 선택·질문 작물의 길잡이 목차에서 찾는다. 길잡이가 없으면 빈 목록
    try:
        links = guide.links_for(q_crop, intent, question, c['queries'])
    except Exception:  # 링크는 덤이라 목차 파일 문제로 답변을 잃지 않는다
        logger.exception('guide links failed')
        links = []
    result = done(intent, text, None, evidence=evidence, guide_links=links)
    if not history:
        cache.set(key, {k: result[1][k] for k in ('intent', 'answer', 'sources', 'guide_links')}, ANSWER_CACHE_SECONDS)
    yield result
