"""Положительные сценарии checkpoint через настоящие F122, без копии public checks."""
import copy
import json
import unittest
from unittest import mock

import sales_template_checkpoint as checkpoint
import sales_template_materialization as f122

import helper_samples as samples


class RoundtripTests(unittest.TestCase):
    def test_en_ru_five_kinds_and_third_locale_keep_exact_text(self):
        names = [
            f"{locale}_{kind}"
            for locale in ("en-GB", "ru-RU")
            for kind in ("INITIAL", "QUESTION", "OBJECTION", "FOLLOWUP", "HANDOFF")
        ] + ["third_locale_synthetic"]
        for name in names:
            sample = samples.case(name)
            source = sample["input"]
            with self.subTest(name=name), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template
            ) as actual:
                blob = checkpoint.capture_checkpoint(
                    source["loaded_registry"],
                    source["bound_language"],
                    template_id=source["template_id"],
                )
                self.assertIs(type(blob), bytes)
                self.assertFalse(blob.startswith(b"\xef\xbb\xbf"))
                self.assertNotEqual(blob[-1:], b"\n")
                self.assertTrue(blob.startswith(b'{"payload":'))
                parsed = json.loads(blob)
                self.assertEqual(parsed["schema_version"], samples.SCHEMA)
                self.assertEqual(parsed["sha256"], samples.digest(parsed["payload"]))
                self.assertEqual(set(parsed["payload"]), {"loaded_registry", "bound_language", "template_id"})
                restored = checkpoint.materialize_checkpoint(
                    blob,
                    expected_registry_version=sample["expected"]["registry_version"],
                    expected_pack_version=sample["expected"]["language_pack_version"],
                )
                self.assertEqual(restored, sample["expected"])
                self.assertEqual(restored["subject"], sample["expected"]["subject"])
                self.assertEqual(restored["body"], sample["expected"]["body"])
                self.assertEqual(restored["fact_ids"], sample["expected"]["fact_ids"])
                self.assertEqual(actual.call_count, 2)
                self.assertIs(actual.call_args_list[0].args[0], source["loaded_registry"])
                self.assertIs(actual.call_args_list[0].args[1], source["bound_language"])
                self.assertEqual(
                    actual.call_args_list[0].kwargs["template_id"],
                    source["template_id"],
                )

    def test_literal_fixture_preserves_unicode_whitespace_and_fact_order(self):
        for name, locale in (
            ("en-GB_HANDOFF", "en-GB"),
            ("ru-RU_HANDOFF", "ru-RU"),
            ("third_locale_synthetic", "de-DE"),
        ):
            sample = samples.case(name)
            literal = samples.apply_literal(sample, locale)
            source = sample["input"]
            with self.subTest(name=name):
                blob = checkpoint.capture_checkpoint(
                    source["loaded_registry"],
                    source["bound_language"],
                    template_id=source["template_id"],
                )
                restored = checkpoint.materialize_checkpoint(
                    blob,
                    expected_registry_version=source["bound_language"]["registry_version"],
                    expected_pack_version=source["bound_language"]["language_pack_version"],
                )
                self.assertEqual(restored["subject"], literal["subject"])
                self.assertEqual(restored["body"], literal["body"])
                self.assertEqual(restored["fact_ids"], literal["fact_ids"])
                self.assertIn("\n", restored["body"])
                self.assertIn("\u00a0", restored["body"])
                payload = json.loads(blob)["payload"]
                self.assertEqual(
                    payload["bound_language"]["approved_template"]["body"],
                    literal["body"],
                )

    def test_dict_key_order_does_not_change_canonical_bytes(self):
        sample = samples.case("ru-RU_INITIAL")
        source = sample["input"]
        flipped = samples.reverse_keys(source)
        self.assertNotEqual(
            list(source["loaded_registry"]),
            list(flipped["loaded_registry"]),
        )
        original = checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id=source["template_id"],
        )
        reordered = checkpoint.capture_checkpoint(
            flipped["loaded_registry"],
            flipped["bound_language"],
            template_id=flipped["template_id"],
        )
        self.assertEqual(original, reordered)
        self.assertEqual(original, samples.canon(json.loads(original)))

    def test_fact_list_order_is_not_normalized(self):
        sample = samples.case("en-GB_HANDOFF")
        source = sample["input"]
        blob = checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id=source["template_id"],
        )
        loaded = source["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["handoff"]
        loaded["fact_ids"] = ["fixture.context", "fixture.contact"]
        source["bound_language"]["approved_template"]["fact_ids"] = [
            "fixture.context",
            "fixture.contact",
        ]
        swapped = checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id="handoff",
        )
        self.assertNotEqual(blob, swapped)
        restored = checkpoint.materialize_checkpoint(
            swapped,
            expected_registry_version="fixture-v1",
            expected_pack_version="en-v1",
        )
        self.assertEqual(restored["fact_ids"], ["fixture.context", "fixture.contact"])

    def test_shared_containers_without_cycle_roundtrip_and_stay_shared(self):
        sample = samples.case("en-GB_HANDOFF")
        source = sample["input"]
        shared = ["fixture.contact", "fixture.context"]
        body = "Shared literal body\n"
        loaded = source["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["handoff"]
        bound_template = source["bound_language"]["approved_template"]
        loaded["fact_ids"] = shared
        bound_template["fact_ids"] = shared
        source["loaded_registry"]["approved_fact_ids"] = shared
        source["bound_language"]["approved_fact_ids"] = shared
        loaded["body"] = body
        bound_template["body"] = body
        self.assertIs(loaded["fact_ids"], bound_template["fact_ids"])
        self.assertIs(loaded["body"], bound_template["body"])
        before = copy.deepcopy(source)
        blob = checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id="handoff",
        )
        self.assertEqual(source["loaded_registry"]["approved_fact_ids"], before["loaded_registry"]["approved_fact_ids"])
        self.assertIs(loaded["fact_ids"], shared)
        first = checkpoint.materialize_checkpoint(
            blob, expected_registry_version="fixture-v1", expected_pack_version="en-v1"
        )
        second = checkpoint.materialize_checkpoint(
            blob, expected_registry_version="fixture-v1", expected_pack_version="en-v1"
        )
        self.assertEqual(first["fact_ids"], shared)
        self.assertIsNot(first, second)
        self.assertIsNot(first["fact_ids"], second["fact_ids"])
        self.assertIsNot(first["fact_ids"], shared)
        first["fact_ids"].append("changed")
        self.assertEqual(second["fact_ids"], ["fixture.contact", "fixture.context"])
        self.assertEqual(shared, ["fixture.contact", "fixture.context"])

    def test_f122_result_object_is_returned_unchanged(self):
        sample = samples.case("en-GB_INITIAL")
        source = sample["input"]
        blob = checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id=source["template_id"],
        )
        original = f122.materialize_bound_template
        seen = []

        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            seen.append(result)
            return result

        with mock.patch.object(f122, "materialize_bound_template", side_effect=wrapper) as actual:
            restored = checkpoint.materialize_checkpoint(
                blob,
                expected_registry_version="fixture-v1",
                expected_pack_version="en-v1",
            )
        self.assertEqual(actual.call_count, 1)
        self.assertIs(restored, seen[0])

    def test_inputs_remain_equal_after_capture(self):
        sample = samples.case("ru-RU_OBJECTION")
        source = sample["input"]
        before = copy.deepcopy(source)
        fact_id = id(source["bound_language"]["approved_fact_ids"])
        checkpoint.capture_checkpoint(
            source["loaded_registry"],
            source["bound_language"],
            template_id=source["template_id"],
        )
        self.assertEqual(source, before)
        self.assertEqual(id(source["bound_language"]["approved_fact_ids"]), fact_id)

    def test_semantically_invalid_but_safe_domain_reaches_real_f122(self):
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            with self.assertRaises(f122.TemplateMaterializationError) as caught:
                checkpoint.capture_checkpoint({}, {}, template_id="")
        self.assertIs(type(caught.exception), f122.TemplateMaterializationError)
        self.assertNotIsInstance(caught.exception, checkpoint.TemplateCheckpointError)
        self.assertEqual(actual.call_count, 1)
        self.assertNotIn("{}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
