"""Motor de decision: scheduling predictivo del dia siguiente.

Cruza el pronostico del clima (24 valores horarios) con el escalon de la
tarifa CFE en el que va a caer el consumo de manana para generar un plan
sugerido: en que horas conviene encender el AC.
"""
from decision_engine.ac_decision import EXCESO_MINIMO_EN_EXCEDENTE_C


def generar_plan_manana(
    pronostico_horario_c: list[float],
    temp_confort_max_c: float,
    escalon_tarifa: str = "basico",
    precio_kwh: float | None = None,
) -> list[dict]:
    """Regresa un plan de 24 entradas: {'hora', 'accion_sugerida', 'razon'}."""
    precio = f" (${precio_kwh}/kWh)" if precio_kwh is not None else ""
    plan = []
    for hora, temp in enumerate(pronostico_horario_c):
        exceso = temp - temp_confort_max_c

        if temp < temp_confort_max_c:
            accion, razon = "sin_cambio", (
                f"Pronostico {temp}C, por debajo del confort ({temp_confort_max_c}C)."
            )
        elif escalon_tarifa == "excedente" and exceso < EXCESO_MINIMO_EN_EXCEDENTE_C:
            accion, razon = "sin_cambio", (
                f"Pronostico {temp}C, solo {exceso:.1f}C sobre el confort y el mes ya "
                f"va en el escalon excedente{precio} -- no se enfria por un exceso leve."
            )
        else:
            accion, razon = "encender", (
                f"Pronostico {temp}C sobre el confort, escalon {escalon_tarifa}{precio}."
            )

        plan.append({"hora": hora, "accion_sugerida": accion, "razon": razon})

    return plan
