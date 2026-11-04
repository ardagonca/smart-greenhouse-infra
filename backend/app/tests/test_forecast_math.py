"""Risk alarmı ve nem/çiy noktası hesabı. pytest ile ya da: python -m app.tests.test_forecast_math"""
import pandas as pd
import numpy as np
from app.public_data import rh_from, dew_c
from app.ml.forecast import alarm_series, THR, OFF


def test_rh_dew_roundtrip():
    rh = rh_from(25.0, 1.2)
    assert abs(rh - 62.1) < 0.5  # es(25°C)=3.17 kPa -> (1-1.2/3.17)*100
    assert abs(dew_c(25.0, 100.0) - 25.0) < 0.1  # %100 nemde çiy noktası = sıcaklık
    assert rh_from(None, 1.0) is None


def test_alarm_hysteresis_and_gap():
    t = pd.date_range("2026-01-01", periods=6, freq="h")
    low, mid, high = THR - 0.1, (THR + OFF) / 2, OFF + 0.1
    # 2 ardışık düşük -> açılır, orta değerde açık kalır, yüksekte kapanır
    assert alarm_series(np.array([low, low, mid, high, high, high]), t).tolist() == [False, True, True, False, False, False]
    # saat boşluğu durumu sıfırlar
    t2 = t.delete(2)
    assert alarm_series(np.array([low, low, low, low, low]), t2).tolist() == [False, True, False, True, True]


if __name__ == "__main__":
    test_rh_dew_roundtrip(); test_alarm_hysteresis_and_gap(); print("OK")
