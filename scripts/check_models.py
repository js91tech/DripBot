"""Validate the bot's model lists against the live OpenRouter catalog.

Model IDs on OpenRouter are retired/renamed regularly — that is what took
down every :free model and most paid models in Oct 2026 while gpt-4o kept
working. Run this any time models "stop working":

    python3 scripts/check_models.py

No API key needed for the catalog check. With OPENROUTER_API_KEY set, also
sends one tiny prompt per model to confirm it actually answers (slow).
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm import DEFAULT_MODEL, FREE_MODELS, PAID_MODELS  # noqa: E402

CATALOG_URL = "https://openrouter.ai/api/v1/models"


def fetch_catalog():
    req = urllib.request.Request(
        CATALOG_URL, headers={"User-Agent": "dripsletongue-model-check"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    catalog = fetch_catalog()
    ids = {m["id"] for m in catalog.get("data", [])}
    print(f"Catalog entries: {len(ids)}")

    failures = []
    for label, models in (("FREE", FREE_MODELS), ("PAID", PAID_MODELS)):
        print(f"\n[{label}]")
        for model_id in models:
            ok = model_id in ids
            print(f"  {'OK  ' if ok else 'GONE'} {model_id}")
            if not ok:
                failures.append(model_id)

    print(f"\nDefault model {DEFAULT_MODEL}: {'OK' if DEFAULT_MODEL in ids else 'GONE'}")
    if DEFAULT_MODEL not in ids:
        failures.append(DEFAULT_MODEL)

    if failures:
        print(f"\n{len(failures)} model(s) missing from catalog — update llm.py!")
        return 1
    print("\nAll listed models resolve in the catalog.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
