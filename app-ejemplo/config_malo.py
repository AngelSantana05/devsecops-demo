"""Configuracion de acceso al bucket S3 (LocalStack) para app-ejemplo.

Las credenciales se leen de variables de entorno -- nunca hardcodeadas en el
repositorio. Ver .env.example para las variables esperadas.
"""
import os

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "http://localhost:4566")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "demo-bucket")
