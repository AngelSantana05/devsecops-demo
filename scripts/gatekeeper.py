"""Gatekeeper: puerta de control previa a un merge dev -> production.

Corre dos verificaciones deterministas:
  1. scan_secrets.py sobre el arbol de trabajo completo.
  2. Validacion de la politica de acceso del bucket S3 declarada en
     infra/bucket_policy_privado.json (la politica realmente usada por el
     proyecto -- infra/bucket_policy_publico.json se mantiene aparte como
     ejemplo documentado de mala configuracion, ver README).

Si cualquiera de las dos falla, bloquea (exit 1) y registra el intento en
pipeline_audit.log. Se puede correr en local antes de un merge, o desde CI
(ver .github/workflows/security-audit.yml).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_secrets  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
POLITICA_CANONICA = RAIZ / "infra" / "bucket_policy_privado.json"
LOG = RAIZ / "pipeline_audit.log"


def check_secretos():
    hallazgos = scan_secrets.escanear_arbol(RAIZ)
    if hallazgos:
        detalle = ", ".join(f"{a}:{l}" for a, l, _ in hallazgos)
        return False, f"FAIL ({detalle})"
    return True, "OK"


def check_politica_bucket():
    if not POLITICA_CANONICA.exists():
        return False, f"FAIL (no existe {POLITICA_CANONICA.name})"
    politica = json.loads(POLITICA_CANONICA.read_text())
    for statement in politica.get("Statement", []):
        principal = statement.get("Principal")
        accion = statement.get("Action")
        acciones = accion if isinstance(accion, list) else [accion]
        if principal == "*" and any(a in ("s3:*", "*") for a in acciones):
            return False, "FAIL (acceso publico con Principal=* y Action=s3:*)"
    return True, "OK"


def registrar(origen, destino, resultado_secretos, resultado_politica, permitido):
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    resultado = "PERMITIDO" if permitido else "BLOQUEADO"
    linea = (
        f"{ts} | {origen}->{destino} | scan_secrets={resultado_secretos} | "
        f"policy_check={resultado_politica} | RESULTADO={resultado}\n"
    )
    with LOG.open("a") as f:
        f.write(linea)
    return linea


def main():
    ci_mode = "--ci" in sys.argv
    origen, destino = "dev", "production"

    ok_secretos, msg_secretos = check_secretos()
    ok_politica, msg_politica = check_politica_bucket()
    permitido = ok_secretos and ok_politica

    linea = registrar(origen, destino, msg_secretos, msg_politica, permitido)
    print(linea.strip())

    if not permitido:
        print("gatekeeper: BLOQUEADO, no se autoriza el merge a production.")
        return 1

    print("gatekeeper: PERMITIDO, merge autorizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
