"""API keys for the optional price and status checks: Claude version.

The Claude plugin never reads API keys from your machine or environment.
Add a key as an **API credential** on your Claude cloud environment instead
(claude.ai/code > environment settings > API credentials, for the service's
host). The agent proxy adds it to each request to that host, after the
request leaves the session, so the key never reaches Claude or these scripts.

Works for SearchApi (www.searchapi.io, Bearer) and Duffel (api.duffel.com,
Bearer). Aviationstack takes its key in the URL, so in Claude live flight
status reads the public Flightradar24 page instead.
"""

WHERE = "an API credential on your Claude cloud environment"


def get(service: str) -> str:
    """Never a key in the Claude version; the cloud environment's proxy adds it."""
    return ""


def missing(service: str, host: str) -> str:
    return f"No {service} key reached {host}. Add {WHERE} for {host}."
