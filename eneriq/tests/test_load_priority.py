import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.load_priority import priorizar_apagado


def test_sin_excedente_no_apaga_nada():
    dispositivos = [{"id": "a", "nombre": "A", "peso_prioridad": 1, "consumo_w": 500}]
    plan = priorizar_apagado(dispositivos, gasto_actual_mxn=1000, presupuesto_mxn=1500, precio_kwh=1.2)
    assert plan == []


def test_apaga_el_de_menor_prioridad_primero():
    dispositivos = [
        {"id": "critico", "nombre": "Refrigerador", "peso_prioridad": 10, "consumo_w": 150},
        {"id": "sacrificable", "nombre": "Enchufe demo", "peso_prioridad": 1, "consumo_w": 1200},
    ]
    plan = priorizar_apagado(dispositivos, gasto_actual_mxn=2000, presupuesto_mxn=1500, precio_kwh=1.2)
    assert len(plan) >= 1
    assert plan[0]["device_id"] == "sacrificable"
