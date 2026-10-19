"""Общие образцы для собственных тестов checkpoint. Не заменяет публичные checks."""
import copy
import hashlib
import json
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parents[3]
CASES = json.loads((PACKAGE / "inputs" / "cases.json").read_text(encoding="utf-8"))
LITERAL = json.loads(
    (PACKAGE / "source" / "tests" / "fixtures" / "checkpoint" / "literal_text.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA = "FIRST_TEMPLATE_CHECKPOINT_V1"
NOW = "2026-10-12T10:00:00+00:00"


def canon(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def case(name):
    for item in CASES:
        if item["name"] == name:
            return copy.deepcopy(item)
    raise KeyError(name)


def binding():
    return json.loads((PACKAGE / "inputs" / "binding.json").read_text(encoding="utf-8"))


def digest(payload):
    return hashlib.sha256(canon(payload)).hexdigest()


def envelope(payload, sha=None):
    return {
        "schema_version": SCHEMA,
        "payload": payload,
        "sha256": digest(payload) if sha is None else sha,
    }


def assert_code(test, code, fn):
    import sales_template_checkpoint as checkpoint

    with test.assertRaises(checkpoint.TemplateCheckpointError) as caught:
        fn()
    test.assertEqual(caught.exception.code, code)
    test.assertEqual(str(caught.exception), code)
    test.assertIsInstance(caught.exception, ValueError)
    return caught.exception


def reverse_keys(value):
    if type(value) is dict:
        return {key: reverse_keys(item) for key, item in reversed(list(value.items()))}
    if type(value) is list:
        return [reverse_keys(item) for item in value]
    return value


def max_container_depth(value, depth):
    if type(value) is dict:
        best = depth
        for item in value.values():
            if type(item) is dict or type(item) is list:
                best = max(best, max_container_depth(item, depth + 1))
        return best
    if type(value) is list:
        best = depth
        for item in value:
            if type(item) is dict or type(item) is list:
                best = max(best, max_container_depth(item, depth + 1))
        return best
    return 0


def nest(levels):
    node = {"leaf": "x"}
    for _ in range(levels - 1):
        node = {"n": node}
    return node


def apply_literal(sample, locale):
    literal = LITERAL[locale]
    template_id = sample["input"]["template_id"]
    loaded = sample["input"]["loaded_registry"]["packs_by_locale"][locale]["templates"][template_id]
    bound = sample["input"]["bound_language"]["approved_template"]
    for target in (loaded, bound):
        target["subject"] = literal["subject"]
        target["body"] = literal["body"]
        target["fact_ids"] = list(literal["fact_ids"])
    return literal


def consumer_ready(sample):
    """Пустая тема не проходит consumer F130; для моста оставляем непрозрачный текст."""
    locale = sample["input"]["bound_language"]["locale"]
    template_id = sample["input"]["template_id"]
    template = sample["input"]["loaded_registry"]["packs_by_locale"][locale]["templates"][template_id]
    if not template["subject"].strip():
        template["subject"] = "Synthetic subject"
    if not template["body"].strip():
        template["body"] = "Synthetic body"
    sample["input"]["bound_language"]["approved_template"] = copy.deepcopy(template)
    sample["input"]["bound_language"]["approved_fact_ids"] = copy.deepcopy(template["fact_ids"])
    return sample
