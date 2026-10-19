"""Own bridge tests: real accepted dependencies, exact ABI, and effect ordering.

Spies call the actual accepted functions. Replacements are used only to inject
an exception whose identity must survive, or to deny forbidden ambient I/O.
"""
import builtins
import copy
import datetime as datetime_module
import http.client
import io
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import time
import types
import unittest
import urllib.request
from contextlib import ExitStack
from unittest import mock

import sales_action_locale as f120
import sales_first_binding as f105
import sales_language_registry as f106
import sales_rules as consumer
import sales_runtime_materialization as f130
import sales_template_checkpoint as checkpoint
import sales_template_materialization as f122

from helper_cases import CASES, ROOT, binding, canonical, consumer_case, make_envelope, now, sample


class BridgeCheckpointTests(unittest.TestCase):
    def capture(self, value):
        return checkpoint.capture_checkpoint(
            value["loaded_registry"], value["bound_language"],
            template_id=value["template_id"],
        )

    def prepare(self, blob, value, config, save, **overrides):
        bound = value["bound_language"]
        arguments = {
            "now": now(), "locale": bound["locale"],
            "required_template_id": value["template_id"],
            "pinned_pack_version": bound["language_pack_version"],
            "save_materials": save,
        }
        arguments.update(overrides)
        return checkpoint.prepare_checkpoint_materials(
            blob, value["loaded_registry"], config, **arguments,
        )

    def assert_code(self, code, action):
        with self.assertRaises(checkpoint.TemplateCheckpointError) as raised:
            action()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(str(raised.exception), code)

    def test_real_chain_all_kinds_en_ru_third_locale_exact_abi_and_identity(self):
        seen_cases = set()
        for index, case in enumerate(CASES):
            with self.subTest(case=case["name"]):
                value, config = consumer_case(index)
                before = copy.deepcopy((value, config))
                blob = self.capture(value)
                blob_before = bytes(blob)
                expected = f122.materialize_bound_template(
                    value["loaded_registry"], value["bound_language"],
                    template_id=value["template_id"],
                )
                clock = now()
                events, observed = [], {}
                marker = object()
                real_runtime = f130.prepare_bound_materials
                real_bind = f130.bind_action_locale
                real_binding = f120.validate_first_binding
                real_current = f130.materialize_bound_template
                real_consumer = f130.validate_materials
                real_decode = checkpoint.materialize_checkpoint
                real_frozen = f122.materialize_bound_template

                def runtime(*args, **kwargs):
                    events.append("F130")
                    self.assertEqual(len(args), 2)
                    self.assertIs(args[0], value["loaded_registry"])
                    self.assertIs(args[1], config)
                    self.assertEqual(set(kwargs), {
                        "now", "locale", "required_template_id",
                        "pinned_pack_version", "save_materials",
                    })
                    self.assertIs(kwargs["now"], clock)
                    self.assertEqual(kwargs["locale"], expected["locale"])
                    self.assertEqual(kwargs["required_template_id"], value["template_id"])
                    self.assertEqual(kwargs["pinned_pack_version"], expected["language_pack_version"])
                    self.assertTrue(callable(kwargs["save_materials"]))
                    self.assertIsNot(kwargs["save_materials"], save)
                    return real_runtime(*args, **kwargs)

                def bind(*args, **kwargs):
                    events.append("F120")
                    self.assertEqual(len(args), 2)
                    self.assertIs(args[0], value["loaded_registry"])
                    self.assertIs(args[1], config)
                    self.assertIs(kwargs["now"], clock)
                    result = real_bind(*args, **kwargs)
                    observed["bound"] = result
                    return result

                def first_binding(*args, **kwargs):
                    events.append("F105")
                    self.assertIs(args[0], config)
                    self.assertIs(kwargs["now"], clock)
                    return real_binding(*args, **kwargs)

                def current(*args, **kwargs):
                    events.append("current F122")
                    self.assertEqual(len(args), 2)
                    self.assertIs(args[0], value["loaded_registry"])
                    self.assertIs(args[1], observed["bound"])
                    self.assertEqual(kwargs, {"template_id": value["template_id"]})
                    result = real_current(*args, **kwargs)
                    observed["current"] = result
                    return result

                def validate(*args, **kwargs):
                    events.append("consumer")
                    self.assertEqual(len(args), 1)
                    self.assertEqual(kwargs, {})
                    self.assertIs(args[0], observed["current"])
                    return real_consumer(*args, **kwargs)

                def decode(*args, **kwargs):
                    events.append("checkpoint decode")
                    self.assertEqual(args, (blob,))
                    self.assertIs(args[0], blob)
                    self.assertEqual(kwargs, {
                        "expected_registry_version": observed["current"]["registry_version"],
                        "expected_pack_version": observed["current"]["language_pack_version"],
                    })
                    return real_decode(*args, **kwargs)

                def frozen(*args, **kwargs):
                    events.append("frozen F122")
                    result = real_frozen(*args, **kwargs)
                    observed["frozen"] = result
                    return result

                def save(*args, **kwargs):
                    events.append("save")
                    self.assertEqual(len(args), 1)
                    self.assertEqual(kwargs, {})
                    self.assertIs(args[0], observed["current"])
                    self.assertIsNot(args[0], observed["frozen"])
                    self.assertEqual(args[0], expected)
                    return marker

                with ExitStack() as stack:
                    spies = [
                        stack.enter_context(mock.patch.object(owner, name, side_effect=spy))
                        for owner, name, spy in [
                            (f130, "prepare_bound_materials", runtime),
                            (f130, "bind_action_locale", bind),
                            (f120, "validate_first_binding", first_binding),
                            (f130, "materialize_bound_template", current),
                            (f130, "validate_materials", validate),
                            (checkpoint, "materialize_checkpoint", decode),
                            (f122, "materialize_bound_template", frozen),
                        ]
                    ]
                    # F130 owns the imported F120 callable. A separate public
                    # F120 call here would be an unauthorized second binding.
                    public_bind = stack.enter_context(mock.patch.object(
                        f120, "bind_action_locale", wraps=f120.bind_action_locale))
                    self.assertIs(self.prepare(blob, value, config, save, now=clock), marker)
                    self.assertEqual([spy.call_count for spy in spies], [1] * len(spies))
                    public_bind.assert_not_called()
                self.assertEqual(events, [
                    "F130", "F120", "F105", "current F122", "consumer",
                    "checkpoint decode", "frozen F122", "save",
                ])
                self.assertEqual((value, config), before)
                self.assertEqual(blob, blob_before)
                seen_cases.add((expected["locale"], expected["kind"]))
        for locale in ("en-GB", "ru-RU"):
            self.assertTrue({(locale, kind) for kind in
                             ("INITIAL", "QUESTION", "OBJECTION", "FOLLOWUP", "HANDOFF")} <= seen_cases)
        self.assertTrue(any(locale not in ("en-GB", "ru-RU") for locale, _ in seen_cases))

    def test_only_callable_preflight_before_f130_and_no_current_arg_revalidation(self):
        with mock.patch.object(f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials) as runtime:
            self.assert_code("INVALID_CHECKPOINT_INPUT", lambda:
                checkpoint.prepare_checkpoint_materials(
                    object(), object(), object(), now=object(), locale=object(),
                    required_template_id=object(), pinned_pack_version=object(),
                    save_materials=object()))
            runtime.assert_not_called()

        error = f120.ActionLocaleError("INVALID_INPUT")
        loaded, config, clock, locale, template_id, pinned, blob = [object() for _ in range(7)]
        save = mock.Mock()
        with mock.patch.object(f130, "prepare_bound_materials", side_effect=error) as runtime, \
             mock.patch.object(checkpoint, "materialize_checkpoint", wraps=checkpoint.materialize_checkpoint) as decode:
            with self.assertRaises(f120.ActionLocaleError) as raised:
                checkpoint.prepare_checkpoint_materials(
                    blob, loaded, config, now=clock, locale=locale,
                    required_template_id=template_id, pinned_pack_version=pinned,
                    save_materials=save)
            self.assertIs(raised.exception, error)
            runtime.assert_called_once()
            args, kwargs = runtime.call_args
            self.assertIs(args[0], loaded)
            self.assertIs(args[1], config)
            for key, expected_value in (("now", clock), ("locale", locale),
                                        ("required_template_id", template_id),
                                        ("pinned_pack_version", pinned)):
                self.assertIs(kwargs[key], expected_value)
            decode.assert_not_called()
            save.assert_not_called()

    def test_real_current_failures_precede_broken_blob_preserve_error_identity(self):
        scenarios = (
            ("binding", f105.FirstBindingError, "INVALID_APPROVAL_REF"),
            ("expired", f105.FirstBindingError, "INVALID_VALIDITY"),
            ("now", f120.ActionLocaleError, "INVALID_INPUT"),
            ("pin", f120.ActionLocaleError, "PACK_VERSION_CHANGED"),
            ("registry", f106.LanguageRegistryError, "INVALID_TEMPLATE"),
            ("consumer", consumer.RuleViolation, "MISSING_SUBJECT"),
        )
        for scenario, error_type, code in scenarios:
            with self.subTest(scenario=scenario):
                value, config = consumer_case()
                overrides = {}
                if scenario == "binding":
                    config["owner_approval_ref"] = ""
                elif scenario == "expired":
                    overrides["now"] = datetime_module.datetime.fromisoformat("2030-01-01T00:00:00+00:00")
                elif scenario == "now":
                    overrides["now"] = datetime_module.datetime(2026, 10, 12, 10)
                elif scenario == "pin":
                    overrides["pinned_pack_version"] = "different-version"
                elif scenario == "registry":
                    value["loaded_registry"]["packs_by_locale"]["ru-RU"]["templates"]["initial"]["kind"] = "UNKNOWN"
                elif scenario == "consumer":
                    value = sample(1)  # Real F122 accepts its literal blank subject.
                before = copy.deepcopy((value, config))
                observed = []
                seam = "validate_materials" if scenario == "consumer" else "bind_action_locale"
                actual = getattr(f130, seam)

                def observe_error(*args, **kwargs):
                    try:
                        return actual(*args, **kwargs)
                    except Exception as exc:
                        observed.append(exc)
                        raise

                save = mock.Mock()
                with mock.patch.object(f130, seam, side_effect=observe_error) as stage, \
                     mock.patch.object(checkpoint, "materialize_checkpoint", wraps=checkpoint.materialize_checkpoint) as decode:
                    with self.assertRaises(error_type) as raised:
                        self.prepare(b"not JSON", value, config, save, **overrides)
                    self.assertEqual(str(raised.exception), code)
                    self.assertEqual(len(observed), 1)
                    self.assertIs(raised.exception, observed[0])
                    stage.assert_called_once()
                    decode.assert_not_called()
                    save.assert_not_called()
                self.assertEqual((value, config), before)

    def test_dependency_sentinel_exceptions_preserved_and_no_save(self):
        value, config = consumer_case()
        blob = self.capture(value)
        stages = (
            (f130, "prepare_bound_materials", RuntimeError("runtime-sentinel")),
            (f120, "validate_first_binding", f105.FirstBindingError("INVALID_VALIDITY")),
            (f120, "build_policy_language_fields", f106.LanguageRegistryError("INVALID_TEMPLATE")),
            (f130, "materialize_bound_template", f122.TemplateMaterializationError("INVALID_TEMPLATE")),
            (f130, "validate_materials", consumer.RuleViolation("MISSING_BODY")),
            (f122, "materialize_bound_template", f122.TemplateMaterializationError("TEMPLATE_CONTENT_MISMATCH")),
        )
        for owner, name, error in stages:
            with self.subTest(owner=owner.__name__, name=name):
                save = mock.Mock()
                with mock.patch.object(owner, name, side_effect=error) as dependency:
                    with self.assertRaises(type(error)) as raised:
                        self.prepare(blob, value, config, save)
                    self.assertIs(raised.exception, error)
                    dependency.assert_called_once()
                    save.assert_not_called()

    def test_checkpoint_rejections_never_reach_external_save(self):
        value, config = consumer_case()
        blob = self.capture(value)
        payload = copy.deepcopy(value)
        envelope = make_envelope(payload)
        wrong_digest = copy.deepcopy(envelope)
        wrong_digest["sha256"] = "0" * 64
        bad_semantics = copy.deepcopy(payload)
        bad_semantics["bound_language"]["approved_template"]["body"] = "rehashed altered text"
        blobs = (
            (bytearray(blob), checkpoint.TemplateCheckpointError, "INVALID_CHECKPOINT_INPUT"),
            (b"not JSON", checkpoint.TemplateCheckpointError, "INVALID_CHECKPOINT_JSON"),
            (b"{}", checkpoint.TemplateCheckpointError, "INVALID_CHECKPOINT_SCHEMA"),
            (b" " + blob, checkpoint.TemplateCheckpointError, "NONCANONICAL_CHECKPOINT"),
            (canonical(wrong_digest), checkpoint.TemplateCheckpointError, "CHECKPOINT_DIGEST_MISMATCH"),
            (b"x" * 1048577, checkpoint.TemplateCheckpointError, "CHECKPOINT_TOO_LARGE"),
            (canonical(make_envelope(bad_semantics)), f122.TemplateMaterializationError, "TEMPLATE_CONTENT_MISMATCH"),
        )
        for rejected_blob, error_type, code in blobs:
            with self.subTest(code=code):
                save = mock.Mock()
                before = copy.deepcopy((value, config, rejected_blob))
                with mock.patch.object(f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials) as runtime, \
                     mock.patch.object(f130, "validate_materials", wraps=f130.validate_materials) as validate:
                    with self.assertRaises(error_type) as raised:
                        self.prepare(rejected_blob, value, config, save)
                    self.assertEqual(str(raised.exception), code)
                    runtime.assert_called_once()
                    validate.assert_called_once()
                    save.assert_not_called()
                self.assertEqual((value, config, rejected_blob), before)

    def test_same_versions_changed_literal_subject_body_or_fact_order_mismatch(self):
        for changed in ("subject", "body", "fact_ids"):
            with self.subTest(changed=changed):
                frozen, config = consumer_case(4)
                blob = self.capture(frozen)
                current = copy.deepcopy(frozen)
                template = current["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["handoff"]
                if changed == "subject":
                    template["subject"] = "  " + template["subject"] + "  "
                elif changed == "body":
                    template["body"] += "\n  {literal} changed current text  "
                else:
                    template["fact_ids"].reverse()
                before = copy.deepcopy((frozen, current, config))
                save = mock.Mock()
                with mock.patch.object(f130, "validate_materials", wraps=f130.validate_materials) as validate:
                    self.assert_code("CHECKPOINT_MATERIALS_MISMATCH", lambda:
                        self.prepare(blob, current, config, save))
                    validate.assert_called_once()
                    save.assert_not_called()
                self.assertEqual((frozen, current, config), before)

    def test_different_id_with_identical_template_text_is_mismatch(self):
        value, config = consumer_case()
        blob = self.capture(value)
        current = copy.deepcopy(value)
        templates = current["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]
        templates["same_text_other_id"] = copy.deepcopy(templates["initial"])
        save = mock.Mock()
        self.assert_code("CHECKPOINT_MATERIALS_MISMATCH", lambda:
            self.prepare(blob, current, config, save, required_template_id="same_text_other_id"))
        save.assert_not_called()

    def test_changed_current_registry_and_pack_versions_are_checkpoint_pin_errors(self):
        for changed, code in (("registry", "CHECKPOINT_REGISTRY_MISMATCH"),
                              ("pack", "CHECKPOINT_PACK_MISMATCH")):
            with self.subTest(changed=changed):
                value, config = consumer_case()
                blob = self.capture(value)
                current = copy.deepcopy(value)
                overrides = {}
                if changed == "registry":
                    current["loaded_registry"]["registry_version"] = "fixture-v2"
                else:
                    current["loaded_registry"]["language_pack_versions"]["en-GB"] = "en-v2"
                    current["loaded_registry"]["packs_by_locale"]["en-GB"]["version"] = "en-v2"
                    config["language_pack_versions"]["en-GB"] = "en-v2"
                    overrides["pinned_pack_version"] = "en-v2"
                save = mock.Mock()
                with mock.patch.object(f130, "validate_materials", wraps=f130.validate_materials) as validate:
                    self.assert_code(code, lambda: self.prepare(blob, current, config, save, **overrides))
                    validate.assert_called_once()
                    save.assert_not_called()

    def test_changed_locale_even_with_shared_pack_version_and_text_is_mismatch(self):
        value, config = consumer_case()
        loaded = value["loaded_registry"]
        for locale in loaded["active_locales"]:
            loaded["language_pack_versions"][locale] = "shared-v1"
            loaded["packs_by_locale"][locale]["version"] = "shared-v1"
            config["language_pack_versions"][locale] = "shared-v1"
        template = copy.deepcopy(loaded["packs_by_locale"]["en-GB"]["templates"]["initial"])
        template["locale"] = "ru-RU"
        loaded["packs_by_locale"]["ru-RU"]["templates"]["initial"] = template
        value["bound_language"]["language_pack_version"] = "shared-v1"
        blob = self.capture(value)
        save = mock.Mock()
        self.assert_code("CHECKPOINT_MATERIALS_MISMATCH", lambda:
            self.prepare(blob, value, config, save, locale="ru-RU"))
        save.assert_not_called()

    def test_callback_result_is_opaque_and_callback_exception_is_not_retried(self):
        class OpaqueOutcome:
            def __bool__(self):
                raise AssertionError("callback outcome must not be interpreted")

            def __iter__(self):
                raise AssertionError("callback outcome must not be inspected")

        value, config = consumer_case()
        blob = self.capture(value)
        outcome = OpaqueOutcome()
        save = mock.Mock(return_value=outcome)
        self.assertIs(self.prepare(blob, value, config, save), outcome)
        save.assert_called_once()

        error = RuntimeError("external callback failed after a possible effect")
        save = mock.Mock(side_effect=error)
        with mock.patch.object(f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials) as runtime, \
             mock.patch.object(checkpoint, "materialize_checkpoint", wraps=checkpoint.materialize_checkpoint) as decode:
            with self.assertRaises(RuntimeError) as raised:
                self.prepare(blob, value, config, save)
            self.assertIs(raised.exception, error)
            runtime.assert_called_once()
            decode.assert_called_once()
            save.assert_called_once()

    def test_saved_materials_are_independent_between_calls_and_from_inputs(self):
        value, config = consumer_case(4)
        before = copy.deepcopy((value, config))
        blob = self.capture(value)
        first = self.prepare(blob, value, config, lambda materials: materials)
        second = self.prepare(blob, value, config, lambda materials: materials)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["fact_ids"], second["fact_ids"])
        first["fact_ids"].append("caller-only")
        first["body"] = "caller change"
        self.assertNotIn("caller-only", second["fact_ids"])
        self.assertNotEqual(first["body"], second["body"])
        self.assertEqual((value, config), before)
        self.assertEqual(self.prepare(blob, value, config, lambda materials: materials), second)

    def test_no_io_during_fresh_module_execution_or_any_public_api(self):
        # Read/compile as test setup. Execute the exact module source under the
        # guards so import-time work and aliases captured on import are covered.
        source_path = ROOT / "source" / "sales_template_checkpoint.py"
        compiled = compile(source_path.read_bytes(), str(source_path), "exec")
        probe = types.ModuleType("_checkpoint_io_probe")
        probe.__file__ = str(source_path)
        value, config = consumer_case(4)
        before = copy.deepcopy((value, config))
        clock = now()
        actual_datetime = datetime_module.datetime
        actual_date = datetime_module.date

        def forbidden(*args, **kwargs):
            raise AssertionError("unexpected ambient I/O, clock, or environment access")

        class GuardDateTime(actual_datetime):
            now = classmethod(forbidden)
            utcnow = classmethod(forbidden)
            today = classmethod(forbidden)

        class GuardDate(actual_date):
            today = classmethod(forbidden)

        targets = (
            (builtins, "open"), (io, "open"), (os, "open"),
            (pathlib.Path, "open"), (socket, "socket"),
            (socket, "create_connection"), (sqlite3, "connect"),
            (subprocess, "Popen"), (os, "system"), (os, "popen"),
            (urllib.request, "urlopen"), (http.client.HTTPConnection, "connect"),
            (time, "time"), (time, "time_ns"), (time, "monotonic"),
            (time, "perf_counter"), (time, "sleep"),
            (os, "getenv"), (os, "urandom"),
            (type(os.environ), "__getitem__"),
        )
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(sys.modules, {probe.__name__: probe}))
            guards = [stack.enter_context(mock.patch.object(owner, name, side_effect=forbidden))
                      for owner, name in targets]
            stack.enter_context(mock.patch.object(datetime_module, "datetime", GuardDateTime))
            stack.enter_context(mock.patch.object(datetime_module, "date", GuardDate))
            exec(compiled, probe.__dict__)
            blob = probe.capture_checkpoint(value["loaded_registry"], value["bound_language"],
                                            template_id=value["template_id"])
            material = probe.materialize_checkpoint(
                blob, expected_registry_version=value["bound_language"]["registry_version"],
                expected_pack_version=value["bound_language"]["language_pack_version"])
            saved = []
            result = probe.prepare_checkpoint_materials(
                blob, value["loaded_registry"], config, now=clock,
                locale=value["bound_language"]["locale"],
                required_template_id=value["template_id"],
                pinned_pack_version=value["bound_language"]["language_pack_version"],
                save_materials=lambda materials: (saved.append(materials), materials)[1])
            self.assertEqual(result, material)
            self.assertEqual(len(saved), 1)
            self.assertIs(result, saved[0])
            for guard in guards:
                guard.assert_not_called()
        self.assertEqual((value, config), before)


if __name__ == "__main__":
    unittest.main()
