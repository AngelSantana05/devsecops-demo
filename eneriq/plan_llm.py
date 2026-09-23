"""Genera una explicacion en lenguaje natural del plan de manana, usando el
LLM local del homelab (Ollama directo, LXC `ai`, ver services/ai-stack.md
del skill homelab-implement).

No le pide al modelo que DECIDA nada -- el motor de reglas
(decision_engine.scheduler) ya genero el plan hora por hora con datos duros
(clima, tarifa, umbral de confort). El LLM solo lo explica en espanol
llano, siguiendo la misma filosofia del resto del homelab: el LLM local es
para contexto/explicaciones, no para tomar decisiones.

**Por que Ollama directo y no el gateway de IA (10.10.10.12:8090):**
probado en vivo 2026-09-22 -- el gateway (`/v1/chat/completions`, con su
loop de tool-calling de HA) se cuelga indefinidamente con este prompt
(200s+ sin respuesta, 0 bytes, ni un log de `[tool]`), mientras que pegarle
directo a Ollama con el mismo prompt responde en ~6s. No hace falta nada
de tool-calling para esta tarea (solo narrar datos que ya vienen dados),
asi que se evita el gateway por completo en vez de debuggear su loop de
herramientas -- pendiente investigar esa causa raiz por separado, ver
memoria `project-homelab-llm-ollama`.

Se corre bajo demanda (boton en el dashboard -> POST /plan/llm/generar en
main.py), no por timer.
"""
import sys
from datetime import date, timedelta

import config
import db
import publish_ha
import requests
import tariff

OLLAMA_URL = "http://10.10.10.12:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b-instruct"


def plan_de_manana(cur) -> list[dict]:
    manana = date.today() + timedelta(days=1)
    cur.execute(
        """SELECT hora, accion_sugerida, razon FROM schedules
           WHERE device_id = 'ac' AND fecha = %s ORDER BY hora""",
        (manana,),
    )
    filas = cur.fetchall()
    return [{"hora": h, "accion_sugerida": a, "razon": r} for h, a, r in filas]


def gasto_hoy(cur) -> float:
    cur.execute(
        """SELECT sum(consumo_w) FROM telemetry
           WHERE tiempo >= date_trunc('day', now()) GROUP BY tiempo"""
    )
    filas = cur.fetchall()
    if not filas:
        return 0.0
    kwh_por_corte = 5.0 / 60.0 / 1000.0
    return round(sum((w or 0.0) * kwh_por_corte * tariff.precio_kwh() for (w,) in filas), 2)


def construir_prompt(plan: list[dict]) -> str:
    inicio_punta, fin_punta = tariff.PERIODO_PUNTA
    horas_encender = [p["hora"] for p in plan if p["accion_sugerida"] == "encender"]
    resumen_plan = "\n".join(
        f"- {p['hora']:02d}:00 -> {p['accion_sugerida']} ({p['razon']})"
        for p in plan
    ) or "(el plan de manana todavia no se genero -- avisa que falta correr el scheduling)"

    return f"""Sos el asistente de EnerIQ, un orquestador de energia domestica.
Ya existe un plan calculado por reglas para manana, hora por hora (no lo
inventes, no cambies los numeros, solo explicalo):

{resumen_plan}

Datos de contexto:
- Umbral de confort configurado: {config.TEMP_CONFORT_MAX_C}C
- Horario tarifa punta (mas cara): {inicio_punta}:00-{fin_punta}:00, ${tariff.PRECIOS_MXN_KWH['punta']}/kWh
- Resto del dia (tarifa base): ${tariff.PRECIOS_MXN_KWH['base']}/kWh
- Horas en las que el plan sugiere encender el aire: {horas_encender if horas_encender else 'ninguna'}

Escribe en espanol, en 4-6 lineas, un plan practico y breve para manana
explicando COMO llegar y mantenerse cerca del umbral de confort de forma
economica (aprovechando horario base, evitando punta cuando se pueda).
Tono directo, como si le hablaras al dueno de la casa. No uses markdown,
no repitas la tabla completa, resume lo importante."""


def main():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            plan = plan_de_manana(cur)
            gasto = gasto_hoy(cur)

        prompt = construir_prompt(plan)
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        plan_texto = data["message"]["content"].strip()

        publish_ha.publicar_plan_llm(plan_texto, OLLAMA_MODEL, gasto)
        print(f"plan_llm: generado via {OLLAMA_MODEL} ({len(plan_texto)} caracteres)")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
