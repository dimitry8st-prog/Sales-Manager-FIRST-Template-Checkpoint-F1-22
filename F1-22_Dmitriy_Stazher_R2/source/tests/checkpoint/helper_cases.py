"""Fresh issued fixtures and independent transport helpers for own tests."""
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "inputs/cases.json").read_text(encoding="utf-8"))


def sample(index=0):
    return copy.deepcopy(CASES[index]["input"])


def expected(index=0):
    return copy.deepcopy(CASES[index]["expected"])


def binding():
    return json.loads((ROOT / "inputs/binding.json").read_text(encoding="utf-8"))


def now():
    return datetime.fromisoformat("2026-10-12T10:00:00+00:00")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def make_envelope(payload):
    return {"schema_version": "FIRST_TEMPLATE_CHECKPOINT_V1",
            "payload": payload,
            "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def consumer_case(index=0):
    """Make the issued noninitial examples pass the real F130 subject check."""
    value = sample(index)
    loaded, bound = value["loaded_registry"], value["bound_language"]
    locale, template_id = bound["locale"], value["template_id"]
    template = loaded["packs_by_locale"][locale]["templates"][template_id]
    if not template["subject"].strip():
        template["subject"] = "Synthetic subject"
        bound["approved_template"]["subject"] = "Synthetic subject"
    config = binding()
    config["default_locale"] = loaded["default_locale"]
    config["allowed_locales"] = copy.deepcopy(loaded["active_locales"])
    config["language_pack_versions"] = copy.deepcopy(loaded["language_pack_versions"])
    return value, config
