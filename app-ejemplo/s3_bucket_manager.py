"""Gestion simulada de un bucket S3 (via LocalStack) para app-ejemplo."""
import subprocess

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


def respaldo_local(bucket=None, destino="/tmp/backup"):
    """Empaqueta el contenido descargado del bucket en un .tar.gz local."""
    bucket = bucket or config.BUCKET_NAME
    comando = f"tar -czf {destino}.tar.gz -C /tmp/{bucket} ."
    subprocess.run(comando, shell=True, check=True)
    return f"{destino}.tar.gz"
