"""Independent transport, precedence, and real-F122 checks for R2.

The boundary builders use matching selected text in the loaded and bound
objects.  The depth probes intentionally reach F122's schema rejection at
depth 64, so transport depth can be tested without inventing a core schema.
"""
import copy
import hashlib
import json
import unittest
from unittest import mock

import sales_template_checkpoint as checkpoint
import sales_template_materialization as f122
import sales_action_locale as f120
import sales_runtime_materialization as f130

from helper_cases import CASES, canonical, expected, make_envelope, sample


MAX_BYTES = 1048576


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class StrSubclass(str):
    pass


class BytesSubclass(bytes):
    pass


def capture(value):
    return checkpoint.capture_checkpoint(**value)


def decode(blob, value=None, **pins):
    value = sample() if value is None else value
    arguments = {
        "expected_registry_version": value["bound_language"]["registry_version"],
        "expected_pack_version": value["bound_language"]["language_pack_version"],
    }
    arguments.update(pins)
    return checkpoint.materialize_checkpoint(blob, **arguments)


def selected_template(value):
    return value["loaded_registry"]["packs_by_locale"][
        value["bound_language"]["locale"]
    ]["templates"][value["template_id"]]


def set_selected(value, field, content):
    selected_template(value)[field] = copy.deepcopy(content)
    value["bound_language"]["approved_template"][field] = copy.deepcopy(content)


def reverse_dict_keys(value):
    if type(value) is dict:
        return {key: reverse_dict_keys(value[key]) for key in reversed(value)}
    if type(value) is list:
        return [reverse_dict_keys(item) for item in value]
    return value


def nested_list(levels):
    value = "leaf"
    for _ in range(levels):
        value = [value]
    return value


def sized_valid_payload(target):
    """Construct a semantic F122 input with an exactly sized envelope."""
    value = sample()
    set_selected(value, "body", "Ж😀")
    remaining = target - len(canonical(make_envelope(value)))
    if remaining % 2:
        # This is another real template, so every change remains valid F106.
        value["loaded_registry"]["packs_by_locale"]["en-GB"][
            "templates"]["question"]["body"] += "x"
        remaining -= 1
    set_selected(value, "body", "Ж😀" + "x" * (remaining // 2))
    blob = canonical(make_envelope(value))
    if len(blob) != target:
        raise AssertionError("incorrect independent size fixture")
    return value, blob


class CodecTests(unittest.TestCase):
    def assert_code(self, code, action):
        with self.assertRaises(checkpoint.TemplateCheckpointError) as caught:
            action()
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        return caught.exception

    def test_all_kinds_en_ru_and_third_locale_real_f122_exact_envelope(self):
        self.assertEqual(len(CASES), 11)
        observed = set()
        for index, case in enumerate(CASES):
            value = sample(index)
            before = copy.deepcopy(value)
            with self.subTest(case=case["name"]), mock.patch.object(
                f122, "materialize_bound_template",
                wraps=f122.materialize_bound_template,
            ) as real:
                blob = capture(value)
                self.assertIs(type(blob), bytes)
                self.assertEqual(blob, canonical(make_envelope(value)))
                self.assertEqual(decode(blob, value), expected(index))
                self.assertEqual(real.call_count, 2)
                first = real.call_args_list[0]
                arguments = dict(zip(("loaded_registry", "bound_language"), first.args))
                arguments.update(first.kwargs)
                self.assertEqual(set(arguments), set(value))
                self.assertIs(arguments["loaded_registry"], value["loaded_registry"])
                self.assertIs(arguments["bound_language"], value["bound_language"])
                self.assertEqual(arguments["template_id"], value["template_id"])
                self.assertEqual(value, before)
            observed.add((value["bound_language"]["locale"], expected(index)["kind"]))
        kinds = {"INITIAL", "QUESTION", "OBJECTION", "FOLLOWUP", "HANDOFF"}
        self.assertTrue({(loc, kind) for loc in ("en-GB", "ru-RU")
                         for kind in kinds}.issubset(observed))
        self.assertIn(("de-DE", "QUESTION"), observed)

    def test_real_f122_decode_result_identity_and_exactly_one_call(self):
        value = sample(4)
        blob = canonical(make_envelope(value))
        result_objects = []
        real = f122.materialize_bound_template

        def observe(*args, **kwargs):
            result = real(*args, **kwargs)
            result_objects.append(result)
            return result

        with mock.patch.object(f122, "materialize_bound_template", side_effect=observe) as spy:
            result = decode(blob, value)
        self.assertEqual(spy.call_count, 1)
        self.assertIs(result, result_objects[0])
        self.assertEqual(result, expected(4))

    def test_codec_never_rebinds_or_calls_runtime_materialization(self):
        value = sample()
        with mock.patch.object(f120, "bind_action_locale", wraps=f120.bind_action_locale) as bind, \
             mock.patch.object(f130, "prepare_bound_materials", wraps=f130.prepare_bound_materials) as runtime:
            blob = capture(value)
            self.assertEqual(decode(blob), expected())
        bind.assert_not_called()
        runtime.assert_not_called()

    def test_capture_root_types_and_subclasses_precede_real_f122(self):
        replacements = {
            "loaded_registry": ([], "text", None, DictSubclass(sample()["loaded_registry"])),
            "bound_language": ([], "text", None, DictSubclass(sample()["bound_language"])),
            "template_id": ([], {}, None, StrSubclass("initial")),
        }
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for field, values in replacements.items():
                for replacement in values:
                    value = sample()
                    value[field] = replacement
                    with self.subTest(field=field, type=type(replacement).__name__):
                        self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: capture(value))
            real.assert_not_called()

    def test_capture_nested_forbidden_types_and_exact_dict_key_types(self):
        forbidden = [0, -1, 1.25, True, False, None, (), ("text",), b"text",
                     bytearray(b"text"), set(), object(), complex(1, 2),
                     DictSubclass(), ListSubclass(["text"]), StrSubclass("text"),
                     {1: "value"}, {StrSubclass("key"): "value"}]
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for replacement in forbidden:
                value = sample()
                value["bound_language"]["approved_template"]["body"] = replacement
                with self.subTest(type=type(replacement).__name__, value=repr(replacement)):
                    self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: capture(value))
            real.assert_not_called()

    def test_surrogates_in_values_keys_and_template_identifier_are_rejected(self):
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for surrogate in ("\ud800", "\udfff", "\ud83d\ude00"):
                for position in ("value", "key", "template_id"):
                    value = sample()
                    if position == "value":
                        set_selected(value, "body", "private" + surrogate)
                    elif position == "key":
                        value["loaded_registry"]["private" + surrogate] = "value"
                    else:
                        value["template_id"] = surrogate
                    with self.subTest(position=position, surrogate=repr(surrogate)):
                        self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: capture(value))
            real.assert_not_called()

    def test_aliasing_without_cycle_is_allowed_and_snapshot_is_independent(self):
        value = sample(4)
        value["bound_language"]["approved_template"] = selected_template(value)
        value["bound_language"]["approved_fact_ids"] = value["loaded_registry"]["approved_fact_ids"]
        blob = capture(value)
        self.assertEqual(blob, canonical(make_envelope(sample(4))))
        selected_template(value)["body"] = "changed after capture"
        value["loaded_registry"]["approved_fact_ids"].append("later.fact")
        self.assertEqual(decode(blob, sample(4)), expected(4))

    def test_direct_list_and_indirect_cycles_are_rejected_before_f122(self):
        direct_dict = {}
        direct_dict["cycle"] = direct_dict
        direct_list = []
        direct_list.append(direct_list)
        indirect = {"child": []}
        indirect["child"].append(indirect)
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for cycle in (direct_dict, direct_list, indirect):
                value = sample()
                value["loaded_registry"]["cycle"] = cycle
                with self.subTest(cycle_type=type(cycle).__name__):
                    self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: capture(value))
            real.assert_not_called()

    def test_capture_depth_64_reaches_real_f122_and_65_does_not(self):
        for deepest, expected_code, calls in ((64, "INVALID_SCHEMA", 1),
                                               (65, "INVALID_CHECKPOINT_INPUT", 0)):
            value = sample()
            # payload=1, loaded_registry=2, then deepest-2 list containers.
            value["loaded_registry"]["depth_probe"] = nested_list(deepest - 2)
            with self.subTest(depth=deepest), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
            ) as real:
                if deepest == 64:
                    with self.assertRaises(f122.TemplateMaterializationError) as caught:
                        capture(value)
                    self.assertEqual(caught.exception.code, expected_code)
                else:
                    self.assert_code(expected_code, lambda: capture(value))
                self.assertEqual(real.call_count, calls)

    def test_decode_depth_uses_payload_root_without_envelope_extra_level(self):
        for deepest in (64, 65):
            value = sample()
            value["loaded_registry"]["depth_probe"] = nested_list(deepest - 2)
            blob = canonical(make_envelope(value))
            with self.subTest(depth=deepest), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
            ) as real:
                if deepest == 64:
                    with self.assertRaises(f122.TemplateMaterializationError) as caught:
                        decode(blob)
                    self.assertEqual(caught.exception.code, "INVALID_SCHEMA")
                    self.assertEqual(real.call_count, 1)
                else:
                    self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(blob))
                    real.assert_not_called()

    def test_blob_exact_bytes_required_before_size_and_parse(self):
        blob = canonical(make_envelope(sample()))
        for bad in (blob.decode("utf-8"), bytearray(blob), memoryview(blob),
                    BytesSubclass(blob), [], None, bytearray(b"x" * (MAX_BYTES + 1))):
            with self.subTest(type=type(bad).__name__):
                self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: decode(bad))

    def test_expected_versions_exact_types_identifier_regex_and_precedence(self):
        invalid = (None, 1, True, [], {}, b"v1", StrSubclass("v1"), "", "_v1",
                   ":v1", "a" * 129, "v 1", "v1\n", "Ж", "v/1", "\ud800")
        for pin in ("expected_registry_version", "expected_pack_version"):
            for bad in invalid:
                with self.subTest(pin=pin, value=repr(bad)):
                    self.assert_code("INVALID_CHECKPOINT_INPUT", lambda: decode(
                        b"x" * (MAX_BYTES + 1), **{pin: bad}))
        for allowed in ("a", "A0_.:-", "a" * 128):
            with self.subTest(valid_identifier=allowed):
                self.assert_code("CHECKPOINT_REGISTRY_MISMATCH", lambda: decode(
                    canonical(make_envelope(sample())), expected_registry_version=allowed))

    def test_strict_utf8_bom_syntax_and_trailing_garbage(self):
        blob = canonical(make_envelope(sample()))
        invalid = (b"", b"\xff", b'"\xc0\xaf"', b'"\xf0\x9f\x98"',
                   b"\xef\xbb\xbf" + blob, blob + b"x", blob + b"{}",
                   blob + b"\x00", blob[:-1], b'{"a":}', b'{"a":"\x01"}')
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for bad in invalid:
                with self.subTest(blob=repr(bad[:40])):
                    self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(bad))
            real.assert_not_called()

    def test_duplicate_keys_at_envelope_payload_and_nested_template_levels(self):
        blob = canonical(make_envelope(sample()))
        invalid = (
            b'{"schema_version":"FIRST_TEMPLATE_CHECKPOINT_V1",' + blob[1:],
            blob.replace(b'"loaded_registry":', b'"loaded_registry":{},"loaded_registry":', 1),
            blob.replace(b'"body":', b'"body":"duplicate","body":', 1),
            b'{"key":"a","k\\u0065y":"b"}',
        )
        for bad in invalid:
            with self.subTest(blob=repr(bad[:60])):
                self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(bad))

    def test_decode_numbers_booleans_null_nonfinite_and_surrogates_are_domain_errors(self):
        for token in (b"0", b"-1", b"1.5", b"true", b"false", b"null", b"NaN",
                      b"Infinity", b"-Infinity", b"1e999", b'"\\ud800"', b'"\\udfff"'):
            # Safe-schema errors cannot hide an unsafe field, even at envelope level.
            for raw in (b'{"extra":' + token + b'}',
                        b'{"payload":{"loaded_registry":{"x":' + token + b'}}}'):
                with self.subTest(token=token, position=raw[:15]):
                    self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(raw))

    def test_exact_envelope_and_payload_schema_types_and_fieldsets(self):
        original = make_envelope(sample())
        variants = []
        for field in original:
            variant = copy.deepcopy(original)
            del variant[field]
            variants.append(("missing_" + field, variant))
        extra = copy.deepcopy(original)
        extra["grant"] = "approved"
        variants.append(("extra_envelope", extra))
        for wrong in ("", "FIRST_TEMPLATE_CHECKPOINT_V2", [], {}):
            variant = copy.deepcopy(original)
            variant["schema_version"] = wrong
            variants.append(("schema_literal_" + repr(wrong), variant))
        for wrong in ([], "payload"):
            variant = copy.deepcopy(original)
            variant["payload"] = wrong
            variants.append(("payload_type_" + repr(wrong), variant))
        for field in original["payload"]:
            variant = copy.deepcopy(original)
            del variant["payload"][field]
            variants.append(("missing_payload_" + field, variant))
            wrong_types = ([], {}) if field == "template_id" else ([], "wrong")
            for wrong in wrong_types:
                variant = copy.deepcopy(original)
                variant["payload"][field] = wrong
                variants.append(("payload_type_" + field + repr(wrong), variant))
        variant = copy.deepcopy(original)
        variant["payload"]["approved"] = "yes"
        variants.append(("extra_payload", variant))
        for wrong in ("", "0" * 63, "0" * 65, "A" * 64, "g" * 64, "0" * 64 + "\n", [], {}):
            variant = copy.deepcopy(original)
            variant["sha256"] = wrong
            variants.append(("digest_shape_" + repr(wrong), variant))
        variants.extend(("root_" + repr(root), root) for root in ([], "text"))
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for name, variant in variants:
                # Pretty encoding deliberately also violates canonicality: schema wins.
                blob = json.dumps(variant, ensure_ascii=False).encode("utf-8")
                with self.subTest(variant=name):
                    self.assert_code("INVALID_CHECKPOINT_SCHEMA", lambda: decode(blob))
            real.assert_not_called()

    def test_parse_domain_precedes_schema_and_canonical_checks(self):
        variant = make_envelope(sample())
        variant["schema_version"] = "wrong_schema"
        variant["payload"]["loaded_registry"]["extra"] = None
        raw = json.dumps(variant).encode("utf-8")
        self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(raw))

    def test_noncanonical_whitespace_key_order_and_escaping_before_digest(self):
        value = sample(5)
        blob = canonical(make_envelope(value))
        envelope = json.loads(blob)
        wrong_digest = copy.deepcopy(envelope)
        wrong_digest["sha256"] = "0" * 64
        noncanonical = (
            blob + b"\n", b" " + blob,
            json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            json.dumps(reverse_dict_keys(envelope), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            json.dumps(wrong_digest).encode("utf-8"),
        )
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            for bad in noncanonical:
                self.assertNotEqual(bad, blob)
                with self.subTest(prefix=repr(bad[:50])):
                    self.assert_code("NONCANONICAL_CHECKPOINT", lambda: decode(
                        bad, value, expected_registry_version="other", expected_pack_version="other"))
            real.assert_not_called()

    def test_digest_is_sha256_of_payload_only_and_mismatch_precedes_f122_pins(self):
        envelope = make_envelope(sample())
        self.assertEqual(envelope["sha256"], hashlib.sha256(canonical(envelope["payload"])).hexdigest())
        for digest in ("0" * 64, hashlib.sha256(canonical({"payload": envelope["payload"]})).hexdigest()):
            envelope["sha256"] = digest
            with self.subTest(digest=digest), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
            ) as real:
                self.assert_code("CHECKPOINT_DIGEST_MISMATCH", lambda: decode(
                    canonical(envelope), expected_registry_version="wrong", expected_pack_version="wrong"))
                real.assert_not_called()

    def test_real_f122_errors_preserve_identity_for_capture_and_rehashed_decode(self):
        for operation in ("capture", "decode"):
            value = sample()
            value["bound_language"]["approved_template"]["body"] = "private changed literal"
            before = copy.deepcopy(value)
            observed_errors = []
            real = f122.materialize_bound_template

            def observe(*args, **kwargs):
                try:
                    return real(*args, **kwargs)
                except Exception as error:
                    observed_errors.append(error)
                    raise

            with self.subTest(operation=operation), mock.patch.object(
                f122, "materialize_bound_template", side_effect=observe,
            ) as spy:
                with self.assertRaises(f122.TemplateMaterializationError) as caught:
                    if operation == "capture":
                        capture(value)
                    else:
                        decode(canonical(make_envelope(value)), value,
                               expected_registry_version="wrong", expected_pack_version="wrong")
                self.assertIs(caught.exception, observed_errors[0])
                self.assertEqual(caught.exception.code, "TEMPLATE_CONTENT_MISMATCH")
                self.assertEqual(str(caught.exception), "TEMPLATE_CONTENT_MISMATCH")
                self.assertEqual(spy.call_count, 1)
                self.assertEqual(value, before)

    def test_semantic_invalidity_is_left_to_real_f122(self):
        for field in ("template_id", "empty_body", "safe_extra"):
            value = sample()
            expected_code = {"template_id": "INVALID_IDENTIFIER", "empty_body": "INVALID_TEMPLATE",
                             "safe_extra": "INVALID_SCHEMA"}[field]
            if field == "template_id":
                value[field] = "not an identifier"
            elif field == "empty_body":
                set_selected(value, "body", " \t\n")
            else:
                value["loaded_registry"]["extra"] = "safe transport value"
            for action in (lambda: capture(value), lambda: decode(canonical(make_envelope(value)))):
                with self.subTest(field=field), mock.patch.object(
                    f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
                ) as real:
                    with self.assertRaises(f122.TemplateMaterializationError) as caught:
                        action()
                    self.assertEqual(caught.exception.code, expected_code)
                    self.assertEqual(real.call_count, 1)

    def test_pin_comparison_after_real_f122_registry_precedes_pack(self):
        blob = canonical(make_envelope(sample()))
        for registry, pack, code in (("wrong", "wrong", "CHECKPOINT_REGISTRY_MISMATCH"),
                                     ("fixture-v1", "wrong", "CHECKPOINT_PACK_MISMATCH")):
            with self.subTest(code=code), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
            ) as real:
                self.assert_code(code, lambda: decode(blob, expected_registry_version=registry,
                                                      expected_pack_version=pack))
                self.assertEqual(real.call_count, 1)

    def test_large_matching_text_at_limit_minus_one_exact_and_plus_one(self):
        for target in (MAX_BYTES - 1, MAX_BYTES, MAX_BYTES + 1):
            value, independently_encoded = sized_valid_payload(target)
            body = selected_template(value)["body"]
            self.assertEqual(body, value["bound_language"]["approved_template"]["body"])
            core_result = f122.materialize_bound_template(**value)
            self.assertEqual(core_result["body"], body)
            with self.subTest(bytes=target), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template,
            ) as real:
                if target <= MAX_BYTES:
                    self.assertEqual(capture(value), independently_encoded)
                    self.assertEqual(decode(independently_encoded, value), core_result)
                    self.assertEqual(real.call_count, 2)
                else:
                    self.assert_code("CHECKPOINT_TOO_LARGE", lambda: capture(value))
                    self.assertEqual(real.call_count, 1)
                    real.reset_mock()
                    self.assert_code("CHECKPOINT_TOO_LARGE", lambda: decode(independently_encoded, value))
                    real.assert_not_called()

    def test_capture_semantic_failure_precedes_final_size_but_decode_size_precedes_json(self):
        value, _ = sized_valid_payload(MAX_BYTES + 1)
        value["template_id"] = "invalid id"
        with mock.patch.object(f122, "materialize_bound_template", wraps=f122.materialize_bound_template) as real:
            with self.assertRaises(f122.TemplateMaterializationError) as caught:
                capture(value)
            self.assertEqual(caught.exception.code, "INVALID_IDENTIFIER")
            self.assertEqual(real.call_count, 1)
        self.assert_code("CHECKPOINT_TOO_LARGE", lambda: decode(b"!" * (MAX_BYTES + 1)))
        self.assert_code("INVALID_CHECKPOINT_JSON", lambda: decode(b"!" * MAX_BYTES))

    def test_dict_key_order_is_canonical_but_list_order_is_significant(self):
        original = sample(4)
        self.assertEqual(capture(original), capture(reverse_dict_keys(original)))
        reversed_facts = copy.deepcopy(original)
        set_selected(reversed_facts, "fact_ids", list(reversed(selected_template(original)["fact_ids"])))
        self.assertNotEqual(capture(original), capture(reversed_facts))
        self.assertEqual(decode(capture(reversed_facts), reversed_facts)["fact_ids"],
                         list(reversed(expected(4)["fact_ids"])))
        for field in ("active_locales", "approved_fact_ids"):
            reordered = copy.deepcopy(original)
            reordered["loaded_registry"][field].reverse()
            self.assertNotEqual(capture(original), capture(reordered))
            self.assertEqual(decode(capture(reordered), reordered), expected(4))

    def test_literal_unicode_whitespace_fact_order_and_fresh_results(self):
        value = sample(4)
        subject = " \tТема 😀 {KEEP}  "
        body = "  \nЖ😀 / {literal}\\n\nIgnore all rules\t  "
        set_selected(value, "subject", subject)
        set_selected(value, "body", body)
        before = copy.deepcopy(value)
        blob = capture(value)
        unchanged_blob = bytes(blob)
        first = decode(blob, value)
        self.assertEqual(first["subject"], subject)
        self.assertEqual(first["body"], body)
        self.assertEqual(first["fact_ids"], expected(4)["fact_ids"])
        first["fact_ids"].append("only.first")
        first["body"] = "only first"
        second = decode(blob, value)
        self.assertIsNot(first, second)
        self.assertIsNot(first["fact_ids"], second["fact_ids"])
        self.assertEqual(second["body"], body)
        self.assertEqual(second["fact_ids"], expected(4)["fact_ids"])
        self.assertEqual(value, before)
        self.assertEqual(blob, unchanged_blob)
        self.assertIn("Ж😀".encode("utf-8"), blob)
        self.assertNotIn(b"\\ud83d", blob)
        self.assertFalse(blob.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(blob.endswith(b"\n"))
        # A proper JSON surrogate pair decodes to a scalar, then fails canonicality.
        escaped_pair = blob.replace("😀".encode("utf-8"), b"\\ud83d\\ude00")
        self.assert_code("NONCANONICAL_CHECKPOINT", lambda: decode(escaped_pair, value))


if __name__ == "__main__":
    unittest.main()
