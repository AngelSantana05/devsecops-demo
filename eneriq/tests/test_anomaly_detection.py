import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.anomaly_detection import detectar_anomalia


def test_consumo_normal_no_dispara_alerta():
    es_anomalia, razon = detectar_anomalia(520.0, 500.0, 30.0)
    assert es_anomalia is False


def test_pico_sobre_el_umbral_dispara_alerta():
    es_anomalia, razon = detectar_anomalia(700.0, 500.0, 30.0)
    assert es_anomalia is True
    assert "40.0%" in razon


def test_sin_historial_no_evalua():
    es_anomalia, razon = detectar_anomalia(500.0, 0.0, 30.0)
    assert es_anomalia is False
