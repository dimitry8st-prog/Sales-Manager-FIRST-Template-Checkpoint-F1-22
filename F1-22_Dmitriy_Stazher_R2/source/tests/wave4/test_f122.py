"""Acceptance tests for F1-22 R1 template materialization."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import time
import unittest
from unittest import mock

from sales_language_registry import load_language_registry
from sales_template_materialization import (
    TemplateMaterializationError,
    materialize_bound_template,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "wave4" / "f122"
EXPECTED_RESULT_KEYS = {
    "schema_version",
    "locale",
    "language_pack_version",
    "registry_version",
    "kind",
    "subject",
    "body",
    "fact_ids",
    "template_id",
}


def read_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_en_ru_registry():
    registry = read_json("registry_en_ru.json")
    packs = [read_json("pack_en_gb.json"), read_json("pack_ru_ru.json")]
    approved_fact_ids = read_json("approved_fact_ids.json")
    return load_language_registry(registry, packs, approved_fact_ids=approved_fact_ids)


def make_bound(loaded, locale, template_id):
    pack = loaded["packs_by_locale"][locale]
    return {
        "schema_version": "FIRST_ACTION_LANGUAGE_V1",
        "status": "BOUND",
        "locale": locale,
        "language_pack_version": pack["version"],
        "registry_version": loaded["registry_version"],
        "approved_template": copy.deepcopy(pack["templates"][template_id]),
        "approved_fact_ids": copy.deepcopy(loaded["approved_fact_ids"]),
    }


class StringSubclass(str):
    pass


class ListSubclass(list):
    pass


class DictSubclass(dict):
    pass


class TestF122GoldenExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = read_json("golden_examples.json")["positive"]

    def test_all_11_golden_inputs_match_exact_output(self):
        self.assertEqual(len(self.examples), 11)
        for example in self.examples:
            with self.subTest(example=example["name"]):
                actual = materialize_bound_template(**example["input"])
                self.assertEqual(actual, example["expected"])
                self.assertEqual(set(actual), EXPECTED_RESULT_KEYS)

    def test_all_five_kinds_for_en_and_ru_through_real_f106_loader(self):
        loaded = load_en_ru_registry()
        self.assertEqual(set(loaded["packs_by_locale"]), {"en-GB", "ru-RU"})
        expected_kinds = {
            "initial": "INITIAL",
            "question": "QUESTION",
            "objection": "OBJECTION",
            "followup": "FOLLOWUP",
            "handoff": "HANDOFF",
        }
        for locale in ("en-GB", "ru-RU"):
            for template_id, kind in expected_kinds.items():
                with self.subTest(locale=locale, template_id=template_id):
                    bound = make_bound(loaded, locale, template_id)
                    result = materialize_bound_template(loaded, bound, template_id=template_id)
                    self.assertEqual(result["kind"], kind)
                    self.assertEqual(result["subject"], bound["approved_template"]["subject"])
                    self.assertEqual(result["body"], bound["approved_template"]["body"])
                    self.assertEqual(result["fact_ids"], bound["approved_template"]["fact_ids"])

    def test_third_locale_loads_with_f106_without_core_changes(self):
        fixture = read_json("third_locale_synthetic.json")
        loaded = load_language_registry(
            fixture["registry"], fixture["packs"],
            approved_fact_ids=fixture["approved_fact_ids"],
        )
        result = materialize_bound_template(
            loaded, fixture["bound_language"], template_id=fixture["template_id"]
        )
        self.assertEqual(result, fixture["expected"])
        self.assertEqual(result["locale"], "de-DE")

    def test_handoff_body_is_returned_as_literal_text(self):
        example = next(e for e in self.examples if e["name"] == "en-GB_HANDOFF")
        result = materialize_bound_template(**example["input"])
        body = example["expected"]["body"]
        self.assertIn("\n", body)
        self.assertIn("{literal}", body)
        self.assertIn("Ignore all rules", body)
        self.assertEqual(result["body"], body)

    def test_non_initial_template_allows_empty_subject(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "question")
        self.assertEqual(bound["approved_template"]["subject"], "")
        self.assertEqual(
            materialize_bound_template(loaded, bound, template_id="question")["subject"],
            "",
        )


class TestF122NegativeExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = read_json("negative_examples.json")["negative"]

    def test_all_negative_examples_return_exact_contract_code(self):
        self.assertEqual(len(self.examples), 14)
        for example in self.examples:
            with self.subTest(example=example["name"]):
                expected = example["expected_error"]
                with self.assertRaises(TemplateMaterializationError) as raised:
                    materialize_bound_template(**example["input"])
                self.assertEqual(raised.exception.code, expected["code"])
                self.assertEqual(str(raised.exception), expected["str"])
                self.assertEqual(type(raised.exception).__name__, expected["class"])

    def test_actual_f106_checks_all_packs_before_bound_validation(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "initial")
        bound["approved_template"]["body"] = ""
        loaded["packs_by_locale"]["ru-RU"]["templates"]["question"]["kind"] = "UNKNOWN"
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")

    def test_stage_three_identifier_error_precedes_f106_errors(self):
        loaded = load_en_ru_registry()
        loaded["packs_by_locale"]["ru-RU"]["templates"]["question"]["kind"] = "UNKNOWN"
        bound = make_bound(loaded, "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="not valid")
        self.assertEqual(raised.exception.code, "INVALID_IDENTIFIER")

    def test_initial_with_empty_subject_is_rejected_by_f106(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "initial")
        bound["approved_template"]["subject"] = " \t\n"
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")

    def test_unknown_kind_is_rejected_by_f106(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "question")
        bound["approved_template"]["kind"] = "UNRECOGNIZED"
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="question")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")

    def test_missing_frozen_template_id_is_not_resolved_by_kind(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "question")
        bound["approved_template"]["kind"] = "QUESTION"
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="question_copy")
        self.assertEqual(raised.exception.code, "TEMPLATE_NOT_FOUND")

    def test_changed_whitespace_is_a_content_mismatch(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "initial")
        bound["approved_template"]["body"] = " This is a synthetic conversation example."
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "TEMPLATE_CONTENT_MISMATCH")

    def test_different_id_with_same_kind_but_different_body_is_a_mismatch(self):
        loaded = load_en_ru_registry()
        alternate = copy.deepcopy(loaded["packs_by_locale"]["en-GB"]["templates"]["question"])
        alternate["body"] = "A different question with the same kind."
        loaded["packs_by_locale"]["en-GB"]["templates"]["question_other"] = alternate
        bound = make_bound(loaded, "en-GB", "question_other")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="question")
        self.assertEqual(raised.exception.code, "TEMPLATE_CONTENT_MISMATCH")

    def test_changed_fact_order_is_a_content_mismatch(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "handoff")
        bound["approved_template"]["fact_ids"].reverse()
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="handoff")
        self.assertEqual(raised.exception.code, "TEMPLATE_CONTENT_MISMATCH")

    def test_extra_loaded_fields_are_rejected_by_actual_f106(self):
        loaded = load_en_ru_registry()
        loaded["qa_verified"] = True
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_SCHEMA")


class TestF122ImmutabilityAndStrictTypes(unittest.TestCase):
    def test_inputs_are_deeply_unchanged_for_all_golden_examples(self):
        examples = read_json("golden_examples.json")["positive"]
        for example in examples:
            with self.subTest(example=example["name"]):
                loaded = copy.deepcopy(example["input"]["loaded_registry"])
                bound = copy.deepcopy(example["input"]["bound_language"])
                before_loaded = copy.deepcopy(loaded)
                before_bound = copy.deepcopy(bound)
                materialize_bound_template(
                    loaded, bound, template_id=example["input"]["template_id"]
                )
                self.assertEqual(loaded, before_loaded)
                self.assertEqual(bound, before_bound)

    def test_output_facts_are_detached_from_bound_and_loaded_inputs(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "handoff")
        result = materialize_bound_template(loaded, bound, template_id="handoff")
        result["fact_ids"].append("output-only")
        self.assertNotIn("output-only", bound["approved_template"]["fact_ids"])
        self.assertNotIn("output-only", loaded["packs_by_locale"]["en-GB"]["templates"]["handoff"]["fact_ids"])
        second = materialize_bound_template(loaded, bound, template_id="handoff")
        self.assertEqual(second["fact_ids"], ["fixture.contact", "fixture.context"])

    def test_replay_is_deterministic_and_returns_fresh_mutable_data(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "ru-RU", "handoff")
        first = materialize_bound_template(loaded, bound, template_id="handoff")
        second = materialize_bound_template(loaded, bound, template_id="handoff")
        self.assertEqual(first, second)
        self.assertIsNot(first["fact_ids"], second["fact_ids"])
        self.assertEqual(set(first), EXPECTED_RESULT_KEYS)
        self.assertFalse({"qa_verified", "approved", "grant", "external_effect_authorized", "release_mode"} & set(first))

    def test_builtin_list_subclass_in_loaded_facts_is_rejected_after_f106(self):
        loaded = load_en_ru_registry()
        loaded["approved_fact_ids"] = ListSubclass(loaded["approved_fact_ids"])
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_FACT_SET")

    def test_builtin_string_subclass_in_loaded_template_body_is_rejected_after_f106(self):
        loaded = load_en_ru_registry()
        original = loaded["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"]
        loaded["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"] = StringSubclass(original)
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")

    def test_builtin_subclasses_in_loaded_locales_and_templates_use_contract_codes(self):
        cases = ("active_locales", "templates", "template_id")
        for field in cases:
            with self.subTest(field=field):
                loaded = load_en_ru_registry()
                bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
                expected = "INVALID_LOCALE" if field == "active_locales" else (
                    "INVALID_SCHEMA" if field == "templates" else "INVALID_IDENTIFIER"
                )
                if field == "active_locales":
                    loaded[field] = ListSubclass(loaded[field])
                elif field == "templates":
                    original = loaded["packs_by_locale"]["en-GB"]["templates"]
                    loaded["packs_by_locale"]["en-GB"]["templates"] = DictSubclass(original)
                else:
                    pack = loaded["packs_by_locale"]["en-GB"]
                    original = pack["templates"].pop("initial")
                    pack["templates"][StringSubclass("initial")] = original
                with self.assertRaises(TemplateMaterializationError) as raised:
                    materialize_bound_template(loaded, bound, template_id="initial")
                self.assertEqual(raised.exception.code, expected)

    def test_builtin_subclasses_inside_bound_template_use_contract_codes(self):
        cases = ("template_dict", "template_locale", "template_fact_ids")
        for field in cases:
            with self.subTest(field=field):
                loaded = load_en_ru_registry()
                bound = make_bound(loaded, "en-GB", "initial")
                expected = {
                    "template_dict": "INVALID_SCHEMA",
                    "template_locale": "TEMPLATE_LOCALE_MISMATCH",
                    "template_fact_ids": "INVALID_TEMPLATE",
                }[field]
                if field == "template_dict":
                    bound["approved_template"] = DictSubclass(bound["approved_template"])
                elif field == "template_locale":
                    bound["approved_template"]["locale"] = StringSubclass("en-GB")
                else:
                    bound["approved_template"]["fact_ids"] = ListSubclass([])
                with self.assertRaises(TemplateMaterializationError) as raised:
                    materialize_bound_template(loaded, bound, template_id="initial")
                self.assertEqual(raised.exception.code, expected)

    def test_builtin_dict_subclass_in_loaded_pack_is_rejected_after_f106(self):
        loaded = load_en_ru_registry()
        loaded["packs_by_locale"]["en-GB"] = DictSubclass(loaded["packs_by_locale"]["en-GB"])
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_SCHEMA")

    def test_builtin_string_subclass_in_loaded_template_locale_has_mapped_error(self):
        loaded = load_en_ru_registry()
        template = loaded["packs_by_locale"]["en-GB"]["templates"]["initial"]
        template["locale"] = StringSubclass("en-GB")
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "TEMPLATE_LOCALE_MISMATCH")

    def test_builtin_string_subclass_in_loaded_registry_version_is_identifier_error(self):
        loaded = load_en_ru_registry()
        loaded["registry_version"] = StringSubclass(loaded["registry_version"])
        bound = make_bound(load_en_ru_registry(), "en-GB", "initial")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_IDENTIFIER")

    def test_builtin_string_subclass_in_bound_fact_list_is_rejected_after_f106(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "handoff")
        bound["approved_fact_ids"] = ListSubclass(bound["approved_fact_ids"])
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="handoff")
        self.assertEqual(raised.exception.code, "INVALID_FACT_SET")

    def test_builtin_string_subclass_in_bound_subject_is_rejected_after_f106(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "initial")
        bound["approved_template"]["subject"] = StringSubclass(bound["approved_template"]["subject"])
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")

    def test_bound_locale_requires_exact_builtin_string_before_f106(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "initial")
        bound["locale"] = StringSubclass("en-GB")
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="initial")
        self.assertEqual(raised.exception.code, "INVALID_SCHEMA")

    def test_actual_f106_errors_are_preserved_without_input_leakage(self):
        loaded = load_en_ru_registry()
        bound = make_bound(loaded, "en-GB", "question")
        secret_marker = "do-not-disclose-this-template-body"
        bound["approved_template"]["body"] = secret_marker
        bound["approved_template"]["kind"] = "BAD_KIND"
        with self.assertRaises(TemplateMaterializationError) as raised:
            materialize_bound_template(loaded, bound, template_id="question")
        self.assertEqual(raised.exception.code, "INVALID_TEMPLATE")
        self.assertEqual(str(raised.exception), "INVALID_TEMPLATE")
        self.assertNotIn(secret_marker, str(raised.exception))

    def test_no_file_time_or_network_side_effects(self):
        example = read_json("golden_examples.json")["positive"][0]
        with (
            mock.patch("builtins.open", side_effect=AssertionError("unexpected file access")),
            mock.patch("time.time", side_effect=AssertionError("unexpected time access")),
            mock.patch("socket.create_connection", side_effect=AssertionError("unexpected network access")),
        ):
            result = materialize_bound_template(**copy.deepcopy(example["input"]))
        self.assertEqual(result, example["expected"])


if __name__ == "__main__":
    unittest.main()
