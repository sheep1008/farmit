"""[5단계] data/results/의 결과로 docs/ml.md 7장에 넣는 표를 markdown으로 출력한다.

사용: python summarize.py
"""
import glob
import json

import pandas as pd

import dataset as E
import run_region as RR
from common import RESULTS

VERDICT = {"0601": "가능", "0501": "가능", "0502": "가능", "0602": "조건부", "1201": "조건부", "0605": "조건부 (제철)",
           "0614N": "보류", "1209K": "예측 불필요"}


def load(pattern):
    out = []
    for f in sorted(glob.glob(str(RESULTS / pattern))):
        d = json.load(open(f, encoding="utf-8"))
        out += d if isinstance(d, list) else [d]
    return out


def md(df):
    return df.to_markdown(index=False)


if __name__ == "__main__":
    mk = {r["code"]: r for r in load("oof_market_*.json")}
    order = [c for c in E.FINAL_ITEMS if c in mk]

    print("### 품목별 결과 (OOF로 피처·시장 선별, 테스트로 확인)\n")
    rows = []
    for c in order:
        r = mk[c]; m = pd.DataFrame(r["markets"])
        rows.append({"품목": r["item"], "시장": len(m), "피처": r["chosen"],
                     "OOF NMAE": f"{r['oof'][r['chosen']]['mean']:.3f}",
                     "OOF 연도별": " / ".join(f"{x:.3f}" for x in r["oof"][r["chosen"]]["years"]),
                     "테스트 NMAE": f"{r['test_chosen']:.3f}", "테스트 기준선 대비 (시장 중앙값)": f"{m.test_gain.median():.0%}",
                     "선별 시장 (OOF)": f"{int(m.eligible.sum())}/{len(m)}",
                     "테스트에서 기준선 이긴 시장": f"{int((m.test_gain > 0).sum())}/{len(m)}", "판단": VERDICT.get(c, "")})
    print(md(pd.DataFrame(rows)))

    allm = pd.concat([pd.DataFrame(mk[c]["markets"]).assign(item=mk[c]["item"]) for c in order])
    print("\n### 선별 규칙 검증\n")
    rule_rows = []
    for name, col in (("최종: 기준선을 3년+ 이김", "eligible"), ("엄격: + OOF NMAE ≤ 0.12, 개선 ≥ 15%", "eligible_strict")):
        s, n = allm[allm[col]], allm[~allm[col]]
        rule_rows.append({"규칙": name, "선별": f"{len(s)}/{len(allm)}",
                          "선별 시장: 테스트 기준선 이김": f"{(s.test_gain > 0).mean():.1%}" if len(s) else "-",
                          "선별 시장: 개선 중앙값": f"{s.test_gain.median():.0%}" if len(s) else "-",
                          "미선별 시장: 개선 중앙값": f"{n.test_gain.median():.0%}" if len(n) else "-"})
    print(md(pd.DataFrame(rule_rows)))
    both = allm[allm.oof_gain > 0]
    print(f"\nOOF에서 기준선을 이긴 시장 중 테스트에서도 이긴 비율: {(both.test_gain > 0).mean():.1%}")

    print("\n### 시장 × 품목 (테스트 NMAE, ●: 최종 규칙으로 선별, ○: 미선별, -: 학습 기준 미달)\n")
    allm["sido"] = allm.whsl_mrkt_cd.map(RR.sido_of)
    allm["v"] = allm.apply(lambda r: f"{'●' if r.eligible else '○'} {r.test_nmae:.3f}", axis=1)
    mat = allm.pivot_table(index=["sido", "name"], columns="item", values="v", aggfunc="first").fillna("-")
    mat = mat[[mk[c]["item"] for c in order]]
    mat["선별 품목 수"] = mat.apply(lambda r: sum(str(v).startswith("●") for v in r), axis=1)
    print(md(mat.reset_index().rename(columns={"sido": "시도", "name": "시장"}).sort_values(["시도", "시장"])))

    pool = load("oof_pool.json")
    if pool:
        print("\n### 전국 묶음 학습 (사과, 대전·충청 4개 시장 OOF)\n")
        p = pool[0]
        print(md(pd.DataFrame([{"학습": k, **{str(y): f"{v:.3f}" for y, v in d["years"].items()}, "평균": f"{d['mean']:.3f}"}
                               for k, d in p.items()])))

    reg = load("oof_region_*.json")
    if reg:
        print("\n### 시도 단위 (시도 안 모든 시장 합산)\n")
        print(md(pd.DataFrame([{"품목": r["item"], "지역": len(r["regions"]),
                                "테스트 NMAE (중앙)": f"{pd.DataFrame(r['regions']).test_nmae.median():.3f}",
                                "기준선 대비 (중앙)": f"{pd.DataFrame(r['regions']).test_gain.median():.0%}",
                                "테스트에서 기준선 이긴 지역": f"{int((pd.DataFrame(r['regions']).test_gain > 0).sum())}/{len(r['regions'])}"}
                               for r in reg])))
    tr = load("region_transfer.json")
    if tr:
        print("\n### 지역 예측을 개별 시장에 옮겨 쓸 때 (테스트, 시장 NMAE 중앙값)\n")
        print(md(pd.DataFrame([{"품목": r["item"], "단위": r["level"], "지역 가격 NMAE": f"{r['region_nmae']:.3f}",
                                "지역→시장 전환": f"{pd.DataFrame(r['transfer']).region_transfer.median():.3f}",
                                "시장별 모델": f"{pd.DataFrame(r['transfer']).market_model.median():.3f}",
                                "전환이 더 나은 시장": f"{(pd.DataFrame(r['transfer']).region_transfer < pd.DataFrame(r['transfer']).market_model).mean():.0%}"}
                               for r in tr])))

    print("\n### 외부 피처 효과 (음수 = 개선)\n")
    prod = {r["code"]: r for r in load("prod_*.json")}
    print(md(pd.DataFrame([{"품목": mk[c]["item"],
                            "날씨 OOF Δ": f"{mk[c]['oof']['공통+날씨']['mean'] - mk[c]['oof']['공통']['mean']:+.4f}",
                            "날씨 테스트 Δ": f"{(mk[c]['test_chosen'] - mk[c]['test_other']) * (1 if mk[c]['chosen'] == '공통+날씨' else -1):+.4f}",
                            "생산량 OOF Δ": f"{prod[c]['d_oof']:+.4f}" if c in prod else "-",
                            "생산량 테스트 Δ": f"{prod[c]['d_test']:+.4f}" if c in prod else "-"} for c in order])))
