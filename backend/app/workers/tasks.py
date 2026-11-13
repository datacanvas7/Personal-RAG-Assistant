from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check proving that broker, worker and result backend are connected."""
    return "pong"
