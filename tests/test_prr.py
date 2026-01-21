from earthcode.prr import load_zipzarr
import numpy as np
import pandas as pd

def test_zipzarr_read():

    url1 = "https://eoresults.esa.int/d/YIPEEO-CROPYIELDS/2015/03/01/yipeeo-cropyields-sentinel1-features/features1.zarr.zip"
    ds1 = load_zipzarr(url1, end_mb=1024*1024)
    assert np.isclose(pd.Series(ds1.sig0_vh_mean_daily.values.flatten()).describe()['mean'], -19.419959)