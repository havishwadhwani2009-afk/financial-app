"""Forecast models. Each exposes fit(X, y_log_ret) and predict(X) -> (prob_up, expected_log_return).
All preprocessing (imputation, scaling) is inside the model and therefore fitted on training rows only.
Hyper-parameters are fixed a priori (never tuned on test periods)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_VERSION = "1"


class BaselineMean:
    """Unconditional historical frequency / mean of the training window."""
    name = "baseline_mean"
    params: dict = {}

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "BaselineMean":
        self.p_ = float(np.mean(y > 0))
        self.mu_ = float(np.mean(y))
        return self

    def predict(self, X: pd.DataFrame):
        n = len(X)
        return np.full(n, self.p_), np.full(n, self.mu_)

    def explain(self, x: pd.Series) -> list[dict]:
        return []


class _Supervised:
    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        return X[self.cols_]

    def _select_columns(self, X: pd.DataFrame) -> list[str]:
        # keep columns with >=60% non-null coverage in TRAINING data only
        return [c for c in X.columns if X[c].notna().mean() >= 0.6]

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        self.cols_ = self._select_columns(X)
        Xt = self._prep(X)
        ok = Xt.notna().any(axis=1).values
        self._fit(Xt[ok], y[ok])
        return self


class LinearModel(_Supervised):
    """L2 logistic regression (direction) + ridge (return). C chosen on synthetic null/signal series (not real data): ~zero skill on random walks, positive when signal exists."""
    name = "linear"
    params = {"logit_C": 0.001, "ridge_alpha": 500.0, "imputer": "median", "scaler": "standard"}

    def _fit(self, X, y):
        self.clf_ = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  LogisticRegression(C=self.params["logit_C"], max_iter=500))
        self.reg_ = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  Ridge(alpha=self.params["ridge_alpha"]))
        yb = (y > 0).astype(int)
        if yb.min() == yb.max():  # degenerate window: constant label
            self.const_ = float(yb[0])
            self.clf_ = None
        else:
            self.const_ = None
            self.clf_.fit(X, yb)
        self.reg_.fit(X, y)

    def predict(self, X):
        Xt = self._prep(X)
        p = (np.full(len(X), self.const_) if self.clf_ is None else self.clf_.predict_proba(Xt)[:, 1])
        return p, self.reg_.predict(Xt)

    def explain(self, x: pd.Series) -> list[dict]:
        """Per-feature contribution to the log-odds of an up move (coefficient x standardised value)."""
        if self.clf_ is None:
            return []
        imp, sc, lr = self.clf_.steps[0][1], self.clf_.steps[1][1], self.clf_.steps[2][1]
        row = pd.DataFrame([x[self.cols_]])
        z = sc.transform(imp.transform(row))[0]
        out = []
        for c, raw, zi, w in zip(self.cols_, row.iloc[0].values, z, lr.coef_[0]):
            out.append({"feature": c, "value": None if pd.isna(raw) else float(raw), "z": float(zi),
                        "contribution": float(zi * w)})
        return sorted(out, key=lambda d: -abs(d["contribution"]))


class ForestModel(_Supervised):
    name = "random_forest"
    params = {"n_estimators": 150, "max_depth": 3, "min_samples_leaf": 60, "random_state": 0}

    def _fit(self, X, y):
        kw = dict(n_estimators=150, max_depth=3, min_samples_leaf=60, random_state=0, n_jobs=1)
        self.imp_ = SimpleImputer(strategy="median").fit(X)
        Xi = self.imp_.transform(X)
        yb = (y > 0).astype(int)
        self.const_ = float(yb[0]) if yb.min() == yb.max() else None
        self.clf_ = None if self.const_ is not None else RandomForestClassifier(**kw).fit(Xi, yb)
        self.reg_ = RandomForestRegressor(**kw).fit(Xi, y)

    def predict(self, X):
        Xi = self.imp_.transform(self._prep(X))
        p = np.full(len(X), self.const_) if self.clf_ is None else self.clf_.predict_proba(Xi)[:, 1]
        return p, self.reg_.predict(Xi)

    def explain(self, x: pd.Series) -> list[dict]:
        if self.clf_ is None:
            return []
        imp = self.clf_.feature_importances_
        return sorted([{"feature": c, "value": None if pd.isna(x[c]) else float(x[c]), "z": None,
                        "contribution": None, "importance": float(i)} for c, i in zip(self.cols_, imp)],
                      key=lambda d: -d["importance"])


REGISTRY = {"baseline_mean": BaselineMean, "linear": LinearModel, "random_forest": ForestModel}
PRIMARY = "linear"
