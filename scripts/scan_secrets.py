"""Escaner casero de secretos, por expresiones regulares, sobre el arbol de trabajo.

Limitacion conocida (documentada en la auditoria): solo revisa el estado actual
de los archivos en disco, NO el historial de git. Un secreto que se agrego y
luego se removio en un commit posterior sigue viviendo en el historial y este
script no lo detecta -- para eso hace falta Gitleaks (ver README).
"""
import re
import sys
from pathlib import Path

PATRONES = {
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "aws_secret_access_key": re.compile(
        r"(?i)aws_secret[a-z_]*\s*=\s*[\"'][A-Za-z0-9/+=]{40}[\"']"
    ),
    "generic_password": re.compile(r"(?i)(password|passwd|pwd)\s*=\s*[\"'][^\"']{4,}[\"']"),
}

EXTENSIONES = {".py", ".json", ".yml", ".yaml", ".env", ".txt", ".cfg", ".ini"}
IGNORAR_DIRS = {".git", "__pycache__", "reports", ".localstack", "node_modules", ".venv", "venv", "site-packages"}


def escanear_arbol(raiz):
    hallazgos = []
    for path in Path(raiz).rglob("*"):
        if not path.is_file():
            continue
        if any(parte in IGNORAR_DIRS for parte in path.parts):
            continue
        if path.suffix not in EXTENSIONES:
            continue
        try:
            texto = path.read_text(errors="ignore")
        except OSError:
            continue
        for tipo, patron in PATRONES.items():
            for match in patron.finditer(texto):
                linea = texto.count("\n", 0, match.start()) + 1
                hallazgos.append((str(path), linea, tipo))
    return hallazgos


def main():
    raiz = sys.argv[1] if len(sys.argv) > 1 else "."
    hallazgos = escanear_arbol(raiz)
    if hallazgos:
        print(f"scan_secrets.py: {len(hallazgos)} posible(s) secreto(s) encontrado(s):")
        for archivo, linea, tipo in hallazgos:
            print(f"  - {archivo}:{linea} ({tipo})")
        return 1
    print("scan_secrets.py: sin hallazgos en el arbol de trabajo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
