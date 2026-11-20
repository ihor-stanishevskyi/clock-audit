"""Entry point when the service runs on AWS Lambda.

Lambda does not run a web server: it invokes a handler with an event. Mangum
translates between that and the ASGI app, so app/main.py stays unchanged and
the same code serves both a normal container and a Lambda function.
"""
from mangum import Mangum

from .main import app

handler = Mangum(app, lifespan="off")
