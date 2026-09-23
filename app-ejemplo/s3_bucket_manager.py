"""Gestion simulada de un bucket S3 (via LocalStack) para app-ejemplo."""
import os
import re
import tarfile
import tempfile

import boto3

import config_malo as config


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.AWS_ACCESS_KEY,
        aws_secret_access_key=config.AWS_SECRET_KEY,
        region_name=config.AWS_REGION,
    )


def crear_bucket(nombre=None):
    client = get_client()
    nombre = nombre or config.BUCKET_NAME
    client.create_bucket(Bucket=nombre)
    return nombre


def subir_objeto(ruta_local, key, bucket=None):
    client = get_client()
    bucket = bucket or config.BUCKET_NAME
    client.upload_file(ruta_local, bucket, key)


def listar_objetos(bucket=None):
    client = get_client()
    bucket = bucket or config.BUCKET_NAME
    resp = client.list_objects_v2(Bucket=bucket)
    return [obj["Key"] for obj in resp.get("Contents", [])]


# Reglas de nombres de bucket de S3: 3-63 caracteres, minusculas, digitos,
# puntos y guiones, empezando y terminando en letra o digito.
NOMBRE_BUCKET_VALIDO = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def respaldo_local(bucket=None, destino=None, directorio_descargas=None):
    """Empaqueta el contenido descargado del bucket en un .tar.gz local.

    Usa el modulo tarfile en vez de invocar `tar` con shell=True (hallazgo
    B602 / CWE-78 de la auditoria): el nombre del bucket ya no pasa por un
    shell, y ademas se valida para que no pueda salirse del directorio de
    descargas con '../'.

    Sin `destino`, el respaldo se crea con tempfile.mkstemp: nombre unico y
    permisos 0600, creado de forma atomica (hallazgo B108 / CWE-377: antes
    siempre era /tmp/backup.tar.gz, una ruta predecible que otro usuario
    podia ocupar antes con un symlink).
    """
    bucket = bucket or config.BUCKET_NAME
    if not NOMBRE_BUCKET_VALIDO.match(bucket) or ".." in bucket:
        raise ValueError(f"Nombre de bucket invalido: {bucket!r}")
    origen = os.path.join(directorio_descargas or tempfile.gettempdir(), bucket)
    if destino is None:
        fd, archivo = tempfile.mkstemp(prefix=f"respaldo-{bucket}-", suffix=".tar.gz")
        os.close(fd)
    else:
        archivo = f"{destino}.tar.gz"
    with tarfile.open(archivo, "w:gz") as tar:
        tar.add(origen, arcname=".")
    return archivo
