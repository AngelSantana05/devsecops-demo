"""Demo end-to-end: crea el bucket, sube un objeto y lo lista, contra LocalStack.

Uso (desde la raiz del repo):
    docker compose up -d
    cd app-ejemplo && python3 demo_flujo.py
"""
import tempfile

import s3_bucket_manager as s3


def main():
    bucket = s3.crear_bucket()
    print(f"Bucket creado: {bucket}")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("archivo de prueba para app-ejemplo\n")
        ruta = f.name

    s3.subir_objeto(ruta, "prueba.txt", bucket=bucket)
    print("Objeto subido: prueba.txt")

    objetos = s3.listar_objetos(bucket=bucket)
    print(f"Objetos en el bucket: {objetos}")


if __name__ == "__main__":
    main()
