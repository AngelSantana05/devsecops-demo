"""Motor de decision: ¿es una anomalia o consumo normal?

Compara la lectura actual contra el promedio historico del dispositivo.
"""


def detectar_anomalia(
    consumo_actual_w: float,
    promedio_historico_w: float,
    umbral_pct: float,
) -> tuple[bool, str]:
    if promedio_historico_w <= 0:
        return False, "Sin historial suficiente para evaluar (promedio en 0)."

    exceso_pct = (consumo_actual_w - promedio_historico_w) / promedio_historico_w * 100

    if exceso_pct >= umbral_pct:
        return True, (
            f"Consumo actual ({consumo_actual_w}W) supera el promedio historico "
            f"({promedio_historico_w:.1f}W) por {exceso_pct:.1f}%, por encima del "
            f"umbral configurado ({umbral_pct}%)."
        )

    return False, (
        f"Consumo actual ({consumo_actual_w}W) dentro de rango normal "
        f"({exceso_pct:+.1f}% vs. promedio historico de {promedio_historico_w:.1f}W)."
    )
