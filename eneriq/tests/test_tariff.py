import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# tariff solo necesita el mes de inicio del verano de config (evita cargar .env)
sys.modules.setdefault("config", types.SimpleNamespace(VERANO_MES_INICIO=4))

import tariff

SEP = date(2026, 9, 15)
DIC = date(2026, 12, 15)


def test_temporadas_monterrey():
    assert tariff.temporada(date(2026, 4, 1)) == "verano"
    assert tariff.temporada(SEP) == "verano"
    assert tariff.temporada(date(2026, 10, 1)) == "fuera de verano"


def test_recibo_verano_por_escalones():
    # 500 kWh en septiembre 2026: 150*1.016 + 150*1.179 + 150*1.515 + 50*4.041
    r = tariff.recibo_mensual(500, SEP)
    assert r["subtotal"] == round(150 * 1.016 + 150 * 1.179 + 150 * 1.515 + 50 * 4.041, 2)
    assert r["total"] == round(r["subtotal"] * 1.16, 2)


def test_escalon_actual_y_limite():
    assert tariff.limite_subsidiado_kwh(SEP) == 450
    assert tariff.limite_subsidiado_kwh(DIC) == 175
    assert tariff.escalon_actual(100, SEP)[0] == "basico"
    assert tariff.escalon_actual(460, SEP)[0] == "excedente"


def test_costo_incremental_depende_de_lo_ya_consumido():
    barato = tariff.costo_incremental(0, 10, SEP)
    caro = tariff.costo_incremental(600, 10, SEP)
    assert caro > 3 * barato
