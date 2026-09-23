import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.ac_decision import decidir_ac


def test_no_enciende_si_ya_hay_confort():
    accion, razon = decidir_ac(24.0, 26.0, "basico", 1.18)
    assert accion == "esperar"


def test_enciende_en_escalon_subsidiado_si_hace_calor():
    accion, razon = decidir_ac(29.0, 26.0, "intermedio bajo", 1.37)
    assert accion == "encender"
    assert "intermedio bajo" in razon


def test_espera_en_excedente_si_el_exceso_es_leve():
    accion, razon = decidir_ac(27.5, 26.0, "excedente", 4.69)
    assert accion == "esperar"
    assert "excedente" in razon


def test_prioriza_confort_en_excedente_si_el_exceso_es_grave():
    accion, razon = decidir_ac(30.0, 26.0, "excedente", 4.69)
    assert accion == "encender"
