"""Motor de decision: scheduling predictivo del dia siguiente.

Cruza el pronostico del clima (24 valores horarios) con la tarifa por hora
para generar un plan sugerido: en que horas conviene encender el AC.
"""
import tariff


def generar_plan_manana(
    pronostico_horario_c: list[float],
    temp_confort_max_c: float,
) -> list[dict]:
    """Regresa un plan de 24 entradas: {'hora', 'accion_sugerida', 'razon'}."""
    plan = []
    for hora, temp in enumerate(pronostico_horario_c):
        periodo = tariff.periodo_actual(hora)
        precio = tariff.precio_kwh(hora)

        if temp < temp_confort_max_c:
            accion, razon = "sin_cambio", (
                f"Pronostico {temp}C, por debajo del confort ({temp_confort_max_c}C)."
            )
        elif periodo == "punta":
            accion, razon = "sin_cambio", (
                f"Pronostico {temp}C sobre el confort, pero horario punta "
                f"(${precio}/kWh) -- se pospone si es posible."
            )
        else:
            accion, razon = "encender", (
                f"Pronostico {temp}C sobre el confort y horario base "
                f"(${precio}/kWh) -- buen momento para enfriar."
            )

        plan.append({"hora": hora, "accion_sugerida": accion, "razon": razon})

    return plan
