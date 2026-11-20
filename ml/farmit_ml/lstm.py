"""LSTM 시퀀스 모델: 같은 시장의 최근 L주 피처 시퀀스 + 시장 임베딩 → h1~h4 로그변화율 동시 예측 (L1 손실).

torch는 이 모듈을 쓸 때만 불러온다. 앙상블 가중치에서 LSTM을 0으로 두면 torch 없이도 돌아간다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .preprocess import Preprocessor, to_target
from .settings import HORIZONS, SEED, THREADS


def _torch():
    import torch
    torch.set_num_threads(THREADS)
    return torch


def build_matrix(df_all: pd.DataFrame, trn: pd.DataFrame, features: list[str], prep_kw: dict) -> pd.DataFrame:
    """전체 행의 피처 행렬. 통계는 trn에서만 계산한다."""
    p = Preprocessor(features, fill="median", scale=True, market_dummies=False, **prep_kw).fit(trn)
    return p.transform(df_all).astype(np.float32)


def sequences(df_all: pd.DataFrame, X: pd.DataFrame, rows: pd.Index, L: int, mkt_idx: dict):
    """rows마다 같은 시장의 직전 L주(해당 주 포함) 피처를 쌓는다. 이력이 L주 미만인 행은 뺀다.

    df_all은 load_data()처럼 시장·주 순 정렬, 인덱스 0..n-1, 주가 빠짐없이 연속이어야 한다.
    mkt_idx: {market_cd: 임베딩 번호}
    """
    torch = _torch()
    if not df_all.index.equals(pd.RangeIndex(len(df_all))):
        raise ValueError("df_all 인덱스는 0..n-1이어야 한다 (load_data() 결과를 그대로 쓴다)")
    pos = df_all.groupby("market_cd").cumcount()
    Xv = X.values
    keep = [i for i in rows if pos[i] >= L - 1]
    seq = np.stack([Xv[i - L + 1: i + 1] for i in keep])
    mk = df_all.loc[keep, "market_cd"].map(mkt_idx).values
    y = np.stack([to_target(df_all.loc[keep], h, "logratio").values for h in HORIZONS], axis=1)
    return pd.Index(keep), torch.tensor(seq), torch.tensor(mk), torch.tensor(y, dtype=torch.float32)


def _net(n_feat: int, n_mkt: int, hidden: int, layers: int, dropout: float, emb: int = 4):
    torch = _torch()
    nn = torch.nn

    class LSTMNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(n_feat, hidden, num_layers=layers, batch_first=True,
                                dropout=dropout if layers > 1 else 0.0)
            self.emb = nn.Embedding(n_mkt, emb)
            self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden + emb, hidden), nn.ReLU(),
                                      nn.Linear(hidden, len(HORIZONS)))

        def forward(self, x, m):
            out, _ = self.lstm(x)
            return self.head(torch.cat([out[:, -1], self.emb(m)], dim=1))

    return LSTMNet()


def train(cfg: dict, seq, mk, y, n_mkt: int, seed: int = SEED):
    torch = _torch()
    torch.manual_seed(seed)
    np.random.seed(seed)
    net = _net(seq.shape[2], n_mkt, cfg["hidden"], cfg["layers"], cfg["dropout"])
    opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    n, bs = len(seq), cfg.get("batch", 64)
    g = torch.Generator().manual_seed(seed)
    for _ in range(cfg["epochs"]):
        net.train()
        perm = torch.randperm(n, generator=g)
        for b in range(0, n, bs):
            idx = perm[b: b + bs]
            opt.zero_grad()
            pred, yy = net(seq[idx], mk[idx]), y[idx]
            mask = ~torch.isnan(yy)
            loss = (pred[mask] - yy[mask]).abs().mean()   # h2~h4 타깃이 없는 최근 행도 h1로 학습한다
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
    return net


def fit_predict(cfg: dict, df_all: pd.DataFrame, trn: pd.DataFrame, tst: pd.DataFrame, features: list[str],
                prep_kw: dict, markets: list[str], seed: int = SEED):
    """trn으로 학습 → tst 행의 h1~h4 가격(원/kg). 반환: (예측한 tst 인덱스, N×4 배열). markets 순서 = 임베딩 번호."""
    torch = _torch()
    mkt_idx = {k: i for i, k in enumerate(markets)}
    X = build_matrix(df_all, trn, features, prep_kw)
    _, s_tr, m_tr, y_tr = sequences(df_all, X, trn.index, cfg["L"], mkt_idx)
    te_idx, s_te, m_te, _ = sequences(df_all, X, tst.index, cfg["L"], mkt_idx)
    net = train(cfg, s_tr, m_tr, y_tr, len(mkt_idx), seed)
    net.eval()
    with torch.no_grad():
        lr = net(s_te, m_te).numpy()
    return te_idx, df_all.loc[te_idx, "price_kg"].values[:, None] * np.exp(lr)


def predict_avg(cfg: dict, df_all, trn, tst, features, prep_kw, n_seeds: int, markets: list[str]) -> np.ndarray:
    """시드 n개 평균 (LSTM은 시드에 따라 흔들린다). 이력이 부족해 못 한 행은 NaN."""
    out = np.full((len(tst), len(HORIZONS)), np.nan)
    preds = [fit_predict(cfg, df_all, trn, tst, features, prep_kw, markets, seed=s) for s in range(n_seeds)]
    idx = preds[0][0]
    out[tst.index.get_indexer(idx)] = np.mean([p for _, p in preds], axis=0)
    return out
