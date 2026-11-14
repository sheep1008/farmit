# 외부 데이터 API 정리

수집기를 만들기 전에 각 API가 무엇을 돌려주는지 정리한 문서다 (K02, REQ-COL-001·003, REQ-NFR-009).
테이블 정의는 `erd.md`, 요구사항은 `requirements.md`가 기준이다.

- 응답 확인: 2026-11-14 `collectors/explore/explore.py`로 API마다 한 번씩 호출해 확인했다. 원본은 `data/explore/`에 저장한다 (커밋하지 않음).
- 호출 방법(주소·파라미터의 함정)은 `ml/experiments`에서 먼저 확인한 것을 따랐다.

| API | 키 | 쓰는 곳 |
|---|---|---|
| aT 정산정보 | `DATA_GO_KR_KEY` | `settle_price`, 예측 학습 |
| 기상청 ASOS 일자료 | `DATA_GO_KR_KEY` | `weather_daily` |
| 한국천문연구원 특일 정보 | `DATA_GO_KR_KEY` | `holiday` |
| KOSIS 과실생산량 | `KOSIS_API_KEY` | `crop_production`, 예측 피처(선택) |

---

## 1. 공통 (data.go.kr)

- **인증키:** 계정당 하나다. API마다 활용신청이 승인돼야 그 API를 부를 수 있다. **승인되지 않은 API는 HTTP 403**을 돌려준다 (같은 키로 실시간 경매는 200, 정산은 활용신청 전 403이었다).
- **키 인코딩:** 포털의 Encoding 키(`%` 포함)는 그대로, Decoding 키는 URL 인코딩해서 붙인다. `urlencode`에 키를 넣으면 Encoding 키가 두 번 인코딩되므로 키는 따로 붙인다 (`collectors/auction/client.py`).
- **응답 모양:** `response.header.{resultCode, resultMsg}`, `response.body.{totalCount, items.item}`.
  - 정상 `resultCode`가 API마다 다르다: aT `0`, 기상청·천문연 `00`.
  - **결과가 1건이면 `item`이 리스트가 아니라 객체로 온다.** 항상 리스트로 바꿔서 쓴다.
  - 키 오류 등은 JSON을 요청해도 XML로 올 수 있다.
- **키 노출:** 요청 URL에 키가 들어가므로 로그에는 URL을 찍지 않는다. 오류는 HTTP 상태 코드·`resultCode`만 남긴다.

## 2. aT 정산정보

`GET https://apis.data.go.kr/B552845/katSale/trades` — 공영도매시장 거래 정산 확정 내역 (다음 날 반영, 2018-01~)

| 파라미터 | 값 | 주의 |
|---|---|---|
| `serviceKey` | 인증키 | |
| `returnType` | `json` | |
| `pageNo`, `numOfRows` | 페이지, 최대 10,000 | |
| `cond[trd_clcln_ymd::GTE]`, `cond[trd_clcln_ymd::LTE]` | `YYYY-MM-DD` | **`EQ`나 `YYYYMMDD`로 주면 0건.** 하루만 받을 때도 GTE·LTE에 같은 날짜 |
| `cond[whsl_mrkt_cd::EQ]` | 시장 코드 | **시장 조건이 없으면 0건.** 전국은 `GTE=100000`, `LTE=999999` |
| `cond[gds_lclsf_cd::EQ]`, `cond[gds_mclsf_cd::EQ]` | 품목 대·중분류 | 품목만 받을 때 |

**응답 필드 (28개, 값은 모두 문자열):** 한 행 = 한 날짜·시장·법인·품목·등급·포장·크기·산지·거래방식 묶음의 합계다. 낙찰 한 건이 아니다.

| 필드 | 뜻 | 예시 (대전오정 2026-10-30) |
|---|---|---|
| `trd_clcln_ymd` | 거래정산일자 | `2026-10-30` |
| `whsl_mrkt_cd`, `whsl_mrkt_nm` | 도매시장 | `250001`, `대전오정` |
| `corp_cd`, `corp_nm` | 도매법인 | `25000102`, `대전청과㈜` |
| `gds_lclsf_cd/nm`, `gds_mclsf_cd/nm`, `gds_sclsf_cd/nm` | 품목 대·중·소분류 | `03` 두류, `05` 강낭콩, `01` 강낭콩(일반) |
| `grd_cd`, `grd_nm` | 등급 | `10`, `.` |
| `sz_cd`, `sz_nm` | 크기 | `100`, `.` |
| `pkg_cd`, `pkg_nm` | 포장 | `101`, `상자` |
| `unit_cd`, `unit_nm`, `unit_qty` | 포장 1개의 단위·양 | `12`, `kg`, `4.000` (4kg 상자) |
| `unit_tot_qty` | 총물량 (`unit_nm` 단위) | `296.000` (kg) |
| `totprc` | 총 거래금액 (원) | `1489500.000` |
| `avgprc`, `hgprc`, `lwprc` | **포장 1개당** 평균·최고·최저가 (원) | `19900`, `26000`, `15000` |
| `plor_cd`, `plor_nm` | 산지 | `250000`, `강원특별자치도 홍천군` |
| `trd_se` | 거래 방식 | `경매`, `정가수의`, `자기계산` 등 |

**하루치 분포 (2026-10-30, 수집 대상 5개 시장 10,124행):**

| 항목 | 결과 | 수집기에서 할 일 |
|---|---|---|
| `unit_nm` | 전부 `kg` | 그래도 `kg`이 아닌 행은 환산하지 않고 원본만 보관한다 (다른 날·품목에는 있을 수 있다) |
| 물량·금액 0 이하 | 50행 | 가격 계산에서 뺀다 |
| `grd_nm` | 특 6,582 · `.`(등급 없음) 1,478 · 상 1,455 · 중 227 · 등외 156 · 보통 72 · 5등 58 · 하 52 · 6~7등 · 무등급 | 등급 이름이 품목마다 다르다. `.`은 등급 없음 |
| `trd_se` | 경매 77% · 정가수의 18% · 자기계산 2% | 경매가 아닌 거래도 들어 있다 |
| 품목 매칭 | `gds_lclsf_cd + gds_mclsf_cd` = `item.at_code` (예 `03`+`05`=`0305` 강낭콩). 97%가 `item` 테이블 품목 | `item`에 없는 품목은 저장하지 않고 건수만 로그에 남긴다 |

**원/kg 변환 (`unit_nm == "kg"`인 행):**

- 가격(원/kg) = `totprc` ÷ `unit_tot_qty`, 물량(kg) = `unit_tot_qty`
- 포장 1개 가격을 kg당으로: `avgprc` ÷ `unit_qty`. 위 계산과의 비율이 중앙값 1.00 (10~90%: 0.94~1.01)으로 같은 값임을 확인했다.
- 원본(포장 단위) 행은 그대로 따로 보관한다 (CLAUDE.md 단위 규칙).

`settle_price` 매핑 (날짜·시장·품목·등급으로 묶은 값):

| `settle_price` | 계산 |
|---|---|
| `trade_date` | `trd_clcln_ymd` |
| `market_id` | `whsl_mrkt_cd` |
| `item_id` | `item.at_code` = `gds_lclsf_cd + gds_mclsf_cd` |
| `grade` | `grd_nm`. 전 등급 합계는 `ALL` |
| `avg_price` | Σ`totprc` ÷ Σ`unit_tot_qty` (물량가중) |
| `min_price`, `max_price` | 묶음 안 행들의 `lwprc ÷ unit_qty` 최소, `hgprc ÷ unit_qty` 최대 |
| `volume_kg` | Σ`unit_tot_qty` |

## 3. 기상청 ASOS 일자료

`GET https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList` — 지상 관측소 일별 관측값 (D-1까지)

| 파라미터 | 값 |
|---|---|
| `serviceKey` | 인증키 |
| `dataType` | `JSON` |
| `dataCd`, `dateCd` | `ASOS`, `DAY` |
| `startDt`, `endDt` | `YYYYMMDD` |
| `stnIds` | 관측소 번호 (예: 대전 133) |
| `pageNo`, `numOfRows` | 관측소 하나·1년(최대 366행)이 한 페이지에 들어가게 999 |

- 관측소 하나·하루 = 1행, 필드 62개. **숫자까지 모두 문자열**이고 관측이 없으면 빈 문자열 `""`이다.
- 2026-10-30 대전: `avgTa` 13.6, `maxTa` 20.3, `minTa` 8.1, `sumRn` 0.0, `avgRhm` 75.4

`weather_daily` 매핑:

| `weather_daily` | 응답 필드 | 주의 |
|---|---|---|
| `station_id` | `stnId` | |
| `obs_date` | `tm` (`YYYY-MM-DD`) | |
| `avg_temp`, `max_temp`, `min_temp` | `avgTa`, `maxTa`, `minTa` | ℃ |
| `rain_mm` | `sumRn` | 빈 값이 올 수 있다 (`ml/experiments/weather.py`가 0으로 채우는 이유). `erd.md`대로 DB에는 0으로 채우지 않고 NULL로 둔다 |
| `humidity` | `avgRhm` | % |

## 4. 한국천문연구원 특일 정보 (공휴일)

`GET https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo`

| 파라미터 | 값 | 주의 |
|---|---|---|
| `ServiceKey` | 인증키 | **대문자 S** (다른 API와 다르다) |
| `_type` | `json` | 없으면 XML |
| `solYear`, `solMonth` | `2026`, `09` | 월은 두 자리. **`solMonth`를 빼면 그해 전체**가 온다 (2026년 22건, 2026-11-14 확인) → 수집기는 연 1건 |
| `numOfRows` | 50 | |

- 2026-09: 3건 (추석 9/24~26). `{"dateKind": "01", "dateName": "추석", "isHoliday": "Y", "locdate": 20260924, "seq": 1}`
- `locdate`는 **숫자**(`20260924`)로 온다. 날짜로 바꿀 때 문자열로 바꾼 뒤 파싱한다.
- 한 달에 공휴일이 1건이면 `item`이 객체로 온다 (1절).

`holiday` 매핑: `holiday_date` ← `locdate`, `name` ← `dateName`. `isHoliday == "Y"`인 것만 넣는다.
- **같은 날 공휴일이 둘**일 수 있다 (2025-05-05 어린이날·부처님오신날). `holiday_date`가 PK라 이름을 `·`로 합쳐 한 행으로 넣는다 (`collectors/weather/holiday.py`).

## 5. KOSIS 과실생산량

`GET https://kosis.kr/openapi/Param/statisticsParameterData.do` (KOSIS 공유서비스, 별도 키)

| 파라미터 | 값 | 주의 |
|---|---|---|
| `apiKey` | `KOSIS_API_KEY` | |
| `method`, `format`, `jsonVD` | `getList`, `json`, `Y` | |
| `orgId`, `tblId` | `101`, `DT_1ET0292` (과실생산량) | |
| `prdSe`, `startPrdDe`, `endPrdDe` | `Y`, 시작·끝 연도 | 연 단위 |
| `itmId`, `objL1` | `ALL`, `00`(전국) | **`objL2`를 넣으면 오류 21** |

- 정상이면 `data.go.kr` 모양이 아니라 **행 리스트**가 바로 온다. 오류면 `{"err": "11", "errMsg": "유효하지 않은 인증KEY입니다."}` 같은 객체다.
- 2024~2025 전국: 70행 = 연도 2 × 항목 35. 항목(`ITM_NM`)은 `과일:지표` 모양이다 — 사과·배·복숭아·포도·감귤·감·단감·떫은감·자두·기타 × 면적(ha)·생산량(톤)·10a당 생산량(kg)
- 값은 `DT`(문자열), 연도 `PRD_DE`, 최종 수정일 `LST_CHN_DE`(2024년 값이 2025-10-29에 공표).
- 저장: `crop_production` (`erd.md` 3절). 생산량은 톤 → kg(×1000, 반올림). 2012~올해를 호출 1건으로 받아 UPSERT (`collectors/weather/kosis.py`). `item`에 하나뿐인 이름만 매칭되므로 감·매실·기타·합계는 건너뛴다.
- 연 1회 공표라 3회 정도면 충분하다. `docs/ml.md` 7장 결과로는 사과 예측에 효과가 작아 우선순위가 낮다.

---

## 6. 호출 한도와 과거 적재 계산

| API | 한도 | 매일 수집 | 과거 적재 (2018-01-01 ~ 2026-11-13, 3,239일) |
|---|---|---|---|
| aT 정산 | 하루 10,000건 (실시간 경매와 별도) | 시장 5곳 × 1건 = 5건 | 아래 계산 |
| ASOS | 마이페이지 활용신청 현황에서 확인 필요 | 관측소 수 × 1 | 관측소 수 × 9년 (예: 53곳 → 477건. `ml/experiments`는 530건을 하루에 받았다) |
| 특일 | 마이페이지 활용신청 현황에서 확인 필요 | 연 1회 1건 (`solMonth` 생략) | 2018~2027 = 10건 |
| KOSIS | 제한 미공개 | 연 1회 | 1~3건 |

**aT 정산 하루 행 수 (2026-10-30, 금):** 서울가락 5,895 · 대전오정 1,555 · 대전노은 1,350 · 청주 864 · 천안 460 = **5개 시장 합계 10,124행**. 모두 1페이지(10,000행) 안에 들어간다.

| 방법 | 호출 수 | 기간 |
|---|---|---|
| A. 시장·날짜마다 1회 (매일 수집과 같은 방식) | 3,239일 × 5 = **16,195건** | 하루 10,000건 한도로 **2일** |
| B. 시장마다 날짜 범위로 묶어 조회 (GTE~LTE, 페이지 넘김) | 전체 행 ÷ 10,000 ≈ 3,239 × 10,124 ÷ 10,000 ≈ **3,300건** | **하루 안** |

- **B를 권한다.** 호출 수는 "받는 날 수"가 아니라 "받는 행 수"에 비례하게 된다. 다만 한 번에 너무 긴 범위를 잡으면 실패했을 때 다시 받는 양이 커지므로 시장별로 **한 달씩** 끊는다 (월 단위 조회는 `ml/experiments`에서 써 본 방식이다).
- 하루치 표본 하나로 계산한 값이다. 명절 전처럼 물량이 많은 날, 과거 연도는 행 수가 다를 수 있다. 적재하면서 `collect_log.api_calls`로 실제 값을 남긴다.
- 품목 조건을 붙이면 품목 수만큼 호출이 늘어나므로, 전 품목을 받은 뒤 `item` 테이블에 있는 품목만 남긴다.
