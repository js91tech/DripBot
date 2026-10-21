#!/usr/bin/env python3
"""Report configured model IDs that OpenRouter no longer serves.

Usage:
  python scripts/check_models.py

Exits 1 when any picker entry is missing, so it can run in CI.
No API key needed: the model list is public.
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.models import FREE_MODELS, IMAGE_MODELS, PAID_MODELS, RETIRED_MODELS

LOCAL_IMAGE_BACKENDS = {"zai-sidecar", "pollinations"}


def fetch_models():
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as resp:
        return {m["id"]: m for m in json.load(resp)["data"]}


def main():
    live = fetch_models()
    problems = []
    for label, entries in (("free", FREE_MODELS), ("paid", PAID_MODELS)):
        for name, model_id in entries:
            if model_id not in live:
                problems.append(f"{label}: {name} ({model_id}) is not on OpenRouter")
    for name, model_id in IMAGE_MODELS:
        if model_id in LOCAL_IMAGE_BACKENDS:
            continue
        model = live.get(model_id)
        if not model:
            problems.append(f"image: {name} ({model_id}) is not on OpenRouter")
        elif "image" not in model["architecture"].get("output_modalities", []):
            problems.append(f"image: {name} ({model_id}) cannot output images")
    for old, new in RETIRED_MODELS.items():
        if new not in live:
            problems.append(f"retired: {old} maps to {new}, which is not on OpenRouter")

    if problems:
        print("\n".join(problems))
        return 1
    print(f"All {len(FREE_MODELS) + len(PAID_MODELS)} chat models and image models are live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
