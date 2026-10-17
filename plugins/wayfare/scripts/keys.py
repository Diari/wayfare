"""API keys for the optional price and status checks: ChatGPT/Codex version.

Scheduled tasks in the ChatGPT desktop app run on your computer. Put keys in
the app's environment, or in a .env file in the Wayfare folder that the
skills load. Each key is sent only to its own service.
"""
import os

WHERE = "an environment variable (or the .env file in your Wayfare folder)"
ENV = {"searchapi": "SEARCHAPI_API_KEY", "aviationstack": "AVIATIONSTACK_ACCESS_KEY", "duffel": "DUFFEL_ACCESS_TOKEN"}


def get(service: str) -> str:
    return os.environ.get(ENV[service], "").strip()


def missing(service: str, host: str) -> str:
    return f"No {service} key: set {ENV[service]} in {WHERE}."
