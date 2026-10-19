"""Мост F130: текущая привязка проверяется до checkpoint, save — один раз после сверки."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

import sales_action_locale as f120
import sales_first_binding as f105
import sales_rules
import sales_runtime_materialization as f130
import sales_template_checkpoint as checkpoint
import sales_template_materialization as f122

import helper_samples as samples

NOW = datetime.fromisoformat(samples.NOW)


def _capture(sample):
    source = sample["input"]
    return checkpoint.capture_checkpoint(
        source["loaded_registry"],
        source["bound_language"],
        template_id=source["template_id"],
    )


def _prepare(blob, loaded, binding, save, **kwargs):
    arguments = {
        "now": NOW,
        "locale": "en-GB",
        "required_template_id": "initial",
        "pinned_pack_version": "en-v1",
        "save_materials": save,
    }
    arguments.update(kwargs)
    return checkpoint.prepare_checkpoint_materials(blob, loaded, binding, **arguments)


class BridgeTests(unittest.TestCase):
    def test_real_chain_order_identity_and_single_external_save(self):
        sample = samples.case("en-GB_INITIAL")
        source = sample["input"]
        blob = _capture(sample)
        order = []
        holder = {}

        def record(name, function):
            def inner(*args, **kwargs):
                order.append(name)
                return function(*args, **kwargs)
            return inner

        def save(materials):
            order.append("save")
            holder["saved"] = materials
            holder["args"] = (materials,)
            return holder.setdefault("marker", object())

        with mock.patch.object(f120, "bind_action_locale", wraps=f120.bind_action_locale) as direct:
            with mock.patch.object(
                f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials
            ) as prepared, mock.patch.object(
                f130, "bind_action_locale", side_effect=record("bind", f130.bind_action_locale)
            ), mock.patch.object(
                f130,
                "materialize_bound_template",
                side_effect=record("f122", f130.materialize_bound_template),
            ), mock.patch.object(
                f130, "validate_materials", side_effect=record("consumer", f130.validate_materials)
            ) as consumer, mock.patch.object(
                checkpoint,
                "materialize_checkpoint",
                side_effect=record("checkpoint", checkpoint.materialize_checkpoint),
            ):
                # consumer wrapper replaces the function, so capture its input inside save via identity below
                result = _prepare(blob, source["loaded_registry"], samples.binding(), save)
        self.assertEqual(order, ["bind", "f122", "consumer", "checkpoint", "save"])
        self.assertEqual(direct.call_count, 0)
        self.assertEqual(prepared.call_count, 1)
        self.assertIs(prepared.call_args.args[0], source["loaded_registry"])
        self.assertIs(result, holder["marker"])
        self.assertEqual(len(holder["args"]), 1)
        self.assertEqual(holder["saved"], sample["expected"])
        self.assertIs(type(holder["saved"]), dict)
        self.assertEqual(consumer.call_count, 1)

    def test_en_ru_kinds_and_synthetic_locale_roundtrip_through_f130(self):
        names = [
            f"{locale}_{kind}"
            for locale in ("en-GB", "ru-RU")
            for kind in ("INITIAL", "QUESTION", "OBJECTION", "FOLLOWUP", "HANDOFF")
        ]
        for name in names:
            sample = samples.consumer_ready(samples.case(name))
            source = sample["input"]
            locale = source["bound_language"]["locale"]
            pack = source["bound_language"]["language_pack_version"]
            with self.subTest(name=name):
                blob = _capture(sample)
                saved = []

                def save(materials, saved=saved):
                    saved.append(materials)
                    return materials

                result = _prepare(
                    blob,
                    source["loaded_registry"],
                    samples.binding(),
                    save,
                    locale=locale,
                    required_template_id=source["template_id"],
                    pinned_pack_version=pack,
                )
                self.assertEqual(len(saved), 1)
                self.assertIs(result, saved[0])
                self.assertEqual(result["locale"], locale)
                self.assertEqual(result["template_id"], source["template_id"])
                self.assertEqual(result["kind"], source["bound_language"]["approved_template"]["kind"])
                self.assertEqual(result["subject"], source["bound_language"]["approved_template"]["subject"])
                self.assertEqual(result["body"], source["bound_language"]["approved_template"]["body"])
                self.assertEqual(result["fact_ids"], source["bound_language"]["approved_template"]["fact_ids"])

        third = samples.consumer_ready(samples.case("third_locale_synthetic"))
        source = third["input"]
        binding = samples.binding()
        binding["default_locale"] = "de-DE"
        binding["allowed_locales"] = ["de-DE"]
        binding["language_pack_versions"] = {"de-DE": "de-v1"}
        blob = _capture(third)
        result = _prepare(
            blob,
            source["loaded_registry"],
            binding,
            lambda materials: materials,
            locale="de-DE",
            required_template_id="question",
            pinned_pack_version="de-v1",
        )
        self.assertEqual(result["locale"], "de-DE")
        self.assertEqual(result["language_pack_version"], "de-v1")
        self.assertEqual(result["registry_version"], "fixture-third-v1")
        self.assertEqual(result["body"], source["bound_language"]["approved_template"]["body"])

    def test_current_failures_do_not_read_checkpoint_or_save(self):
        sample = samples.case("en-GB_INITIAL")
        loaded = sample["input"]["loaded_registry"]
        question = samples.case("en-GB_QUESTION")["input"]["loaded_registry"]
        expired = datetime(2030, 1, 1, tzinfo=timezone.utc)
        with mock.patch.object(
            checkpoint, "materialize_checkpoint", wraps=checkpoint.materialize_checkpoint
        ) as reader:
            calls = []
            with self.assertRaises(f105.FirstBindingError):
                _prepare(
                    b"bad",
                    loaded,
                    samples.binding(),
                    lambda materials: calls.append(materials),
                    now=expired,
                )
            self.assertEqual(calls, [])
            self.assertEqual(reader.call_count, 0)
            with self.assertRaises(sales_rules.RuleViolation) as consumer_error:
                _prepare(
                    b"bad",
                    question,
                    samples.binding(),
                    lambda materials: calls.append(materials),
                    required_template_id="question",
                )
            self.assertEqual(str(consumer_error.exception), "MISSING_SUBJECT")
            self.assertEqual(calls, [])
            self.assertEqual(reader.call_count, 0)

    def test_noncallable_save_fails_before_f130(self):
        sample = samples.case("en-GB_INITIAL")
        expired = datetime(2030, 1, 1, tzinfo=timezone.utc)
        with mock.patch.object(
            f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials
        ) as prepared:
            for callback in (None, 1, "save"):
                with self.subTest(callback=type(callback).__name__):
                    samples.assert_code(
                        self,
                        "INVALID_CHECKPOINT_INPUT",
                        lambda callback=callback: _prepare(
                            b"bad",
                            sample["input"]["loaded_registry"],
                            samples.binding(),
                            callback,
                            now=expired,
                        ),
                    )
            self.assertEqual(prepared.call_count, 0)

    def test_same_version_text_change_and_other_id_do_not_save(self):
        sample = samples.case("en-GB_INITIAL")
        source = sample["input"]
        blob = _capture(sample)
        changed = copy.deepcopy(source["loaded_registry"])
        body = changed["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"]
        changed["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"] = body + " "
        self.assertEqual(changed["registry_version"], source["loaded_registry"]["registry_version"])
        self.assertEqual(
            changed["language_pack_versions"],
            source["loaded_registry"]["language_pack_versions"],
        )
        calls = []
        samples.assert_code(
            self,
            "CHECKPOINT_MATERIALS_MISMATCH",
            lambda: _prepare(blob, changed, samples.binding(), lambda materials: calls.append(materials)),
        )
        self.assertEqual(calls, [])

        other = copy.deepcopy(source["loaded_registry"])
        initial = other["packs_by_locale"]["en-GB"]["templates"]["initial"]
        other["packs_by_locale"]["en-GB"]["templates"]["other"] = copy.deepcopy(initial)
        samples.assert_code(
            self,
            "CHECKPOINT_MATERIALS_MISMATCH",
            lambda: _prepare(
                blob,
                other,
                samples.binding(),
                lambda materials: calls.append(materials),
                required_template_id="other",
            ),
        )
        self.assertEqual(calls, [])

    def test_current_version_drift_uses_pin_order_and_skips_save(self):
        sample = samples.case("en-GB_INITIAL")
        source = sample["input"]
        blob = _capture(sample)
        calls = []
        drifted_registry = copy.deepcopy(source["loaded_registry"])
        drifted_registry["registry_version"] = "fixture-v2"
        samples.assert_code(
            self,
            "CHECKPOINT_REGISTRY_MISMATCH",
            lambda: _prepare(
                blob,
                drifted_registry,
                samples.binding(),
                lambda materials: calls.append(materials),
            ),
        )
        drifted_pack = copy.deepcopy(source["loaded_registry"])
        drifted_pack["language_pack_versions"]["en-GB"] = "en-v2"
        drifted_pack["packs_by_locale"]["en-GB"]["version"] = "en-v2"
        binding = samples.binding()
        binding["language_pack_versions"]["en-GB"] = "en-v2"
        samples.assert_code(
            self,
            "CHECKPOINT_PACK_MISMATCH",
            lambda: _prepare(
                blob,
                drifted_pack,
                binding,
                lambda materials: calls.append(materials),
                pinned_pack_version="en-v2",
            ),
        )
        self.assertEqual(calls, [])

    def test_callback_error_is_the_same_object_and_is_not_retried(self):
        sample = samples.case("ru-RU_INITIAL")
        source = sample["input"]
        blob = _capture(sample)
        marker = RuntimeError("uncertain external effect")
        calls = []

        def save(materials):
            calls.append(materials)
            raise marker

        with mock.patch.object(
            f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials
        ) as prepared:
            with self.assertRaises(RuntimeError) as caught:
                _prepare(
                    blob,
                    source["loaded_registry"],
                    samples.binding(),
                    save,
                    locale="ru-RU",
                    required_template_id="initial",
                    pinned_pack_version="ru-v1",
                )
        self.assertIs(caught.exception, marker)
        self.assertEqual(len(calls), 1)
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(calls[0]["locale"], "ru-RU")

    def test_rehashed_damage_inside_bridge_does_not_save(self):
        sample = samples.case("en-GB_INITIAL")
        parsed = json.loads(_capture(sample))
        parsed["payload"]["bound_language"]["approved_template"]["body"] = "tampered literal"
        damaged = samples.canon(samples.envelope(parsed["payload"]))
        calls = []
        with self.assertRaises(f122.TemplateMaterializationError) as caught:
            _prepare(
                damaged,
                sample["input"]["loaded_registry"],
                samples.binding(),
                lambda materials: calls.append(materials),
            )
        self.assertEqual(caught.exception.code, "TEMPLATE_CONTENT_MISMATCH")
        self.assertIs(type(caught.exception), f122.TemplateMaterializationError)
        self.assertEqual(calls, [])

    def test_bridge_does_not_mutate_inputs_or_touch_files(self):
        sample = samples.case("en-GB_FOLLOWUP")
        sample = samples.consumer_ready(sample)
        source = sample["input"]
        blob = _capture(sample)
        before_loaded = copy.deepcopy(source["loaded_registry"])
        before_binding = samples.binding()
        binding = copy.deepcopy(before_binding)
        nested = id(source["loaded_registry"]["active_locales"])
        with mock.patch("builtins.open", side_effect=AssertionError("open")):
            result = _prepare(
                blob,
                source["loaded_registry"],
                binding,
                lambda materials: materials,
                required_template_id="followup",
            )
        self.assertEqual(source["loaded_registry"], before_loaded)
        self.assertEqual(binding, before_binding)
        self.assertEqual(id(source["loaded_registry"]["active_locales"]), nested)
        self.assertEqual(result["template_id"], "followup")
        self.assertEqual(blob, _capture(sample))


if __name__ == "__main__":
    unittest.main()
