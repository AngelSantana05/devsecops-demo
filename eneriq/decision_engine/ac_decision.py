"""Motor de decision: ¿prender el AC ahora o esperar?

Entradas: tarifa actual, temperatura interior/exterior, umbral de confort.
Salida: ('encender' | 'esperar', razon).
"""


def decidir_ac(
    temp_interior_c: float,
    temp_confort_max_c: float,
    periodo_tarifa: str,
    precio_kwh: float,
) -> tuple[str, str]:
    if temp_interior_c < temp_confort_max_c:
        return "esperar", (
            f"Temperatura interior ({temp_interior_c}C) por debajo del umbral de "
            f"confort ({temp_confort_max_c}C) -- no hace falta enfriar."
        )

    exceso = temp_interior_c - temp_confort_max_c

    if periodo_tarifa == "punta":
        if exceso >= 3.0:
            return "encender", (
                f"Temperatura interior {temp_interior_c}C supera el confort por "
                f"{exceso:.1f}C -- se prioriza el confort pese a estar en horario "
                f"punta (${precio_kwh}/kWh)."
            )
        return "esperar", (
            f"Temperatura interior {temp_interior_c}C apenas {exceso:.1f}C sobre "
            f"el confort y es horario punta (${precio_kwh}/kWh) -- se espera a "
            f"tarifa base para evitar el costo alto."
        )

    return "encender", (
        f"Temperatura interior {temp_interior_c}C supera el confort "
        f"({temp_confort_max_c}C) y es horario base (${precio_kwh}/kWh) -- "
        f"se enciende sin penalizacion de costo."
    )
