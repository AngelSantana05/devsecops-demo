import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.scheduler import generar_plan_manana


def test_genera_24_horas():
    pronostico = [20.0] * 24
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0)
    assert len(plan) == 24
    assert all(p["accion_sugerida"] == "sin_cambio" for p in plan)


def test_sugiere_encender_en_hora_calurosa_y_escalon_subsidiado():
    pronostico = [20.0] * 24
    pronostico[15] = 27.0
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0, escalon_tarifa="basico")
    assert plan[15]["accion_sugerida"] == "encender"


def test_en_excedente_solo_enfria_con_calor_fuerte():
    pronostico = [20.0] * 24
    pronostico[9] = 27.0   # exceso leve
    pronostico[15] = 33.0  # exceso fuerte
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0, escalon_tarifa="excedente")
    assert plan[9]["accion_sugerida"] == "sin_cambio"
    assert plan[15]["accion_sugerida"] == "encender"
