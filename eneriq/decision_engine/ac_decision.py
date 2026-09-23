"""Motor de decision: ¿prender el AC ahora o esperar?

Entradas: temperatura interior, umbral de confort y el escalon de la tarifa
CFE en el que cae el siguiente kWh del mes (ver tariff.py).
Salida: ('encender' | 'esperar', razon).

En la Tarifa 1C el precio no depende de la hora sino del consumo acumulado del
mes: una vez en el escalon excedente, cada kWh cuesta ~4 veces el basico. Ahi
solo se enfria si el calor es fuerte.
"""

EXCESO_MINIMO_EN_EXCEDENTE_C = 3.0


def decidir_ac(
    temp_interior_c: float,
    temp_confort_max_c: float,
    escalon_tarifa: str,
    precio_kwh: float,
) -> tuple[str, str]:
    if temp_interior_c < temp_confort_max_c:
        return "esperar", (
            f"Temperatura interior ({temp_interior_c}C) por debajo del umbral de "
            f"confort ({temp_confort_max_c}C) -- no hace falta enfriar."
        )

    exceso = temp_interior_c - temp_confort_max_c

    if escalon_tarifa == "excedente":
        if exceso >= EXCESO_MINIMO_EN_EXCEDENTE_C:
            return "encender", (
                f"Temperatura interior {temp_interior_c}C supera el confort por "
                f"{exceso:.1f}C -- se prioriza el confort aunque el consumo del mes "
                f"ya esta en el escalon excedente (${precio_kwh}/kWh)."
            )
        return "esperar", (
            f"Temperatura interior {temp_interior_c}C apenas {exceso:.1f}C sobre "
            f"el confort y el consumo del mes ya esta en el escalon excedente "
            f"(${precio_kwh}/kWh) -- no vale la pena enfriar por un exceso leve."
        )

    return "encender", (
        f"Temperatura interior {temp_interior_c}C supera el confort "
        f"({temp_confort_max_c}C) y el consumo del mes sigue en el escalon "
        f"{escalon_tarifa} (${precio_kwh}/kWh) -- se enciende."
    )
