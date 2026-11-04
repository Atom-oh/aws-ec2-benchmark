"""Django (WSGI) single-module app — web framework benchmark.

No middleware, DEBUG off: measures Django's request/URL-resolve/response path the way a
production API view runs, without session/CSRF/auth overhead. Same endpoint spec as fastapi_app.py.
"""
import hashlib
import platform
from importlib.metadata import version

from django.conf import settings

settings.configure(
    DEBUG=False,
    ALLOWED_HOSTS=["*"],
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[],
    INSTALLED_APPS=[],
    SECRET_KEY="benchmark-only-not-secret",
    USE_TZ=True,
)

from django.core.wsgi import get_wsgi_application  # noqa: E402
from django.http import HttpResponse, JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402

SEED = b"benchmark-seed"
ROUNDS = 2000
VERSION = (
    f"python {platform.python_version()} django {version('django')} gunicorn {version('gunicorn')}"
)


def plaintext(request):
    return HttpResponse("Hello, World!", content_type="text/plain")


def json_view(request):
    return JsonResponse({"message": "Hello, World!"})


def compute(request):
    h = SEED
    for _ in range(ROUNDS):
        h = hashlib.sha256(h).digest()
    return HttpResponse(h.hex(), content_type="text/plain")


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def version_view(request):
    return HttpResponse(VERSION, content_type="text/plain")


urlpatterns = [
    path("plaintext", plaintext),
    path("json", json_view),
    path("compute", compute),
    path("health", health),
    path("version", version_view),
]

application = get_wsgi_application()
