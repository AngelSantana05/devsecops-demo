import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.scheduler import generar_plan_manana


def test_genera_24_horas():
    pronostico = [20.0] * 24
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0)
    assert len(plan) == 24
    assert all(p["accion_sugerida"] == "sin_cambio" for p in plan)


def test_sugiere_encender_en_hora_calurosa_y_base():
    pronostico = [20.0] * 24
    pronostico[10] = 30.0  # 10am, tarifa base (fuera de 18-22)
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0)
    assert plan[10]["accion_sugerida"] == "encender"


def test_pospone_en_hora_calurosa_y_punta():
    pronostico = [20.0] * 24
    pronostico[19] = 30.0  # 7pm, tarifa punta
    plan = generar_plan_manana(pronostico, temp_confort_max_c=26.0)
    assert plan[19]["accion_sugerida"] == "sin_cambio"
