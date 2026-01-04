import os
from celery import Celery
from flask import Flask

# Create Flask app for Celery
def make_app():
    app = Flask(__name__)
    app.config["REDIS_URL"] = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return app

# Create Celery instance
def make_celery():
    flask_app = make_app()
    celery_app = Celery(
        flask_app.import_name,
        backend=flask_app.config["REDIS_URL"],
        broker=flask_app.config["REDIS_URL"]
    )
    celery_app.conf.update(flask_app.config)
    return celery_app