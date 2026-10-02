"""SYNTHETIC test data generators. Used ONLY in automated tests; never written to the app database
that the UI reads."""
import numpy as np
import pandas as pd


def make_prices(n=1500, seed=0, drift=0.0003, vol=0.01, momentum=0.0, latent=0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n)
    r = np.zeros(n)
    mu = 0.0  # persistent latent drift (AR(1), phi=0.98) -> trend-following features carry real signal
    for i in range(n):
        prev = r[i - 1] if i else 0.0
        mu = 0.98 * mu + latent * rng.standard_normal()
        r[i] = drift + mu + momentum * prev + vol * rng.standard_normal()
    p = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"adj_close": p, "volume": rng.integers(1e6, 2e6, n)}, index=idx)
