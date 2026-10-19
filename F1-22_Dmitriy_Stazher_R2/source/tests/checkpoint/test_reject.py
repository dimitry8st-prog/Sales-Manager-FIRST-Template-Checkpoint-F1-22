"""Отказы codec: domain, разбор, приоритет ошибок, границы глубины и размера."""
import ast
import copy
import json
import unittest
from unittest import mock

import sales_template_checkpoint as checkpoint
import sales_template_materialization as f122

import helper_samples as samples


def _blob():
    sample = samples.case("en-GB_INITIAL")
    source = sample["input"]
    return checkpoint.capture_checkpoint(
        source["loaded_registry"],
        source["bound_language"],
        template_id=source["template_id"],
    )


def _materialize(blob, registry="fixture-v1", pack="en-v1"):
    return checkpoint.materialize_checkpoint(
        blob,
        expected_registry_version=registry,
        expected_pack_version=pack,
    )


class DomainAndParserTests(unittest.TestCase):
    def test_forbidden_types_and_subclasses_never_call_f122(self):
        sample = samples.case("en-GB_INITIAL")
        source = sample["input"]
        secret = "TOPSECRET-CHECKPOINT-INPUT"

        class DictSub(dict):
            pass

        class ListSub(list):
            pass

        class StrSub(str):
            pass

        loaded = source["loaded_registry"]
        bound = source["bound_language"]
        cases = [
            (DictSub(loaded), bound, "initial"),
            (loaded, DictSub(bound), "initial"),
            (loaded, bound, StrSub("initial")),
            (None, bound, "initial"),
            (loaded, None, "initial"),
            (loaded, bound, None),
            ({"n": 1, "secret": secret}, {}, "initial"),
            ({"flag": True}, {}, "initial"),
            ({"empty": None}, {}, "initial"),
            ({"pair": (secret,)}, {}, "initial"),
            ({"items": ListSub([secret])}, {}, "initial"),
            ({StrSub("key"): secret}, {}, "initial"),
            ({"bad": secret + "\ud800"}, {}, "initial"),
            ({"\ud800": secret}, {}, "initial"),
        ]
        for loaded_arg, bound_arg, template_id in cases:
            with self.subTest(template_id=type(template_id).__name__), mock.patch.object(
                f122, "materialize_bound_template", wraps=f122.materialize_bound_template
            ) as actual:
                error = samples.assert_code(
                    self,
                    "INVALID_CHECKPOINT_INPUT",
                    lambda: checkpoint.capture_checkpoint(
                        loaded_arg, bound_arg, template_id=template_id
                    ),
                )
                self.assertNotIn(secret, str(error))
                self.assertEqual(actual.call_count, 0)

    def test_cycles_rejected_and_diamond_alias_is_not_a_cycle(self):
        cycle = {}
        cycle["self"] = cycle
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.capture_checkpoint(cycle, {}, template_id="initial"),
        )
        left = {}
        right = {"left": left}
        left["right"] = right
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.capture_checkpoint({"box": left}, {}, template_id="initial"),
        )
        box = []
        box.append(box)
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.capture_checkpoint({"box": box}, {}, template_id="initial"),
        )
        shared = {"leaf": "kept"}
        diamond = {"left": {"item": shared}, "right": {"item": shared}}
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            with self.assertRaises(f122.TemplateMaterializationError):
                checkpoint.capture_checkpoint(diamond, {"other": shared}, template_id="initial")
        self.assertEqual(actual.call_count, 1)

    def test_depth_budget_includes_payload_root_and_stops_before_f122(self):
        def payload(levels):
            return {
                "loaded_registry": samples.nest(levels),
                "bound_language": {"ok": "x"},
                "template_id": "initial",
            }

        exactly = payload(63)
        over = payload(64)
        self.assertEqual(samples.max_container_depth(exactly, 1), 64)
        self.assertEqual(samples.max_container_depth(over, 1), 65)
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            with self.assertRaises(f122.TemplateMaterializationError):
                checkpoint.capture_checkpoint(
                    exactly["loaded_registry"],
                    exactly["bound_language"],
                    template_id=exactly["template_id"],
                )
            self.assertEqual(actual.call_count, 1)
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            samples.assert_code(
                self,
                "INVALID_CHECKPOINT_INPUT",
                lambda: checkpoint.capture_checkpoint(
                    over["loaded_registry"],
                    over["bound_language"],
                    template_id=over["template_id"],
                ),
            )
            self.assertEqual(actual.call_count, 0)

        def packed(levels):
            return samples.canon(
                samples.envelope(samples.nest(levels), sha="a" * 64)
            )

        self.assertEqual(samples.max_container_depth(samples.nest(64), 1), 64)
        self.assertEqual(samples.max_container_depth(samples.nest(65), 1), 65)
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(packed(64)),
        )
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_JSON",
            lambda: _materialize(packed(65)),
        )

    def test_duplicate_keys_bom_utf8_surrogate_and_trailing_junk(self):
        valid = _blob()
        secret = "TOPSECRET-CHECKPOINT-INPUT"
        nested = (
            b'{"schema_version":"FIRST_TEMPLATE_CHECKPOINT_V1",'
            b'"payload":{"bound_language":{"z":"1","z":"1"},'
            b'"loaded_registry":{},"template_id":"t"},'
            b'"sha256":"' + b"ab" * 32 + b'"}'
        )
        envelope_dup = (
            b'{"schema_version":"FIRST_TEMPLATE_CHECKPOINT_V1",'
            b'"schema_version":"FIRST_TEMPLATE_CHECKPOINT_V1",'
            b'"payload":{"bound_language":{},"loaded_registry":{},"template_id":"t"},'
            b'"sha256":"' + b"cd" * 32 + b'"}'
        )
        surrogate = (
            b'{"schema_version":"FIRST_TEMPLATE_CHECKPOINT_V1",'
            b'"payload":{"bound_language":{},"loaded_registry":{},"template_id":"\\uD800"},'
            b'"sha256":"' + b"a" * 64 + b'"}'
        )
        samples_and_codes = [
            (nested, "INVALID_CHECKPOINT_JSON"),
            (envelope_dup, "INVALID_CHECKPOINT_JSON"),
            (b"\xef\xbb\xbf" + valid, "INVALID_CHECKPOINT_JSON"),
            (b"\xff", "INVALID_CHECKPOINT_JSON"),
            (b'{"a":"\xc0\x80"}', "INVALID_CHECKPOINT_JSON"),
            (b'{"a":NaN}', "INVALID_CHECKPOINT_JSON"),
            (b'{"a":Infinity}', "INVALID_CHECKPOINT_JSON"),
            (b'{"a":-Infinity}', "INVALID_CHECKPOINT_JSON"),
            (valid + b" ", "INVALID_CHECKPOINT_JSON"),
            (valid + b"\n", "INVALID_CHECKPOINT_JSON"),
            (b"{}{}", "INVALID_CHECKPOINT_JSON"),
            (surrogate, "INVALID_CHECKPOINT_JSON"),
        ]
        for blob, code in samples_and_codes:
            with self.subTest(blob=blob[:24]):
                error = samples.assert_code(self, code, lambda blob=blob: _materialize(blob))
                self.assertNotIn(secret, str(error))
        samples.assert_code(
            self,
            "NONCANONICAL_CHECKPOINT",
            lambda: _materialize(b" " + valid),
        )
        number_root = json.dumps({"payload": 1, "secret": secret}).encode()
        error = samples.assert_code(
            self, "INVALID_CHECKPOINT_JSON", lambda: _materialize(number_root)
        )
        self.assertNotIn(secret, str(error))

    def test_schema_extras_missing_and_digest_shape(self):
        sample = samples.case("en-GB_QUESTION")
        source = sample["input"]
        payload = {
            "loaded_registry": source["loaded_registry"],
            "bound_language": source["bound_language"],
            "template_id": source["template_id"],
        }
        extra = samples.envelope(payload)
        extra["note"] = "extra"
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(samples.canon(extra)),
        )
        numeric_extra = samples.envelope(payload)
        numeric_extra["note"] = 1
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_JSON",
            lambda: _materialize(samples.canon(numeric_extra)),
        )
        missing = samples.envelope(payload)
        del missing["sha256"]
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(samples.canon(missing)),
        )
        wrong_literal = samples.envelope(payload)
        wrong_literal["schema_version"] = "FIRST_TEMPLATE_CHECKPOINT_V2"
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(samples.canon(wrong_literal)),
        )
        upper = samples.envelope(payload)
        upper["sha256"] = upper["sha256"].upper()
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(samples.canon(upper)),
        )
        list_registry = copy.deepcopy(payload)
        list_registry["loaded_registry"] = []
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_SCHEMA",
            lambda: _materialize(samples.canon(samples.envelope(list_registry))),
        )

    def test_error_priority_when_several_defects_exist(self):
        valid = _blob()
        parsed = json.loads(valid)

        class StrSub(str):
            pass

        class BytesSub(bytes):
            pass

        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.materialize_checkpoint(
                b"x" * 1048577,
                expected_registry_version="",
                expected_pack_version="en-v1",
            ),
        )
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.materialize_checkpoint(
                bytearray(valid),
                expected_registry_version="fixture-v1",
                expected_pack_version="en-v1",
            ),
        )
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.materialize_checkpoint(
                BytesSub(valid),
                expected_registry_version="fixture-v1",
                expected_pack_version="en-v1",
            ),
        )
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_INPUT",
            lambda: checkpoint.materialize_checkpoint(
                valid,
                expected_registry_version=StrSub("fixture-v1"),
                expected_pack_version="en-v1",
            ),
        )
        samples.assert_code(
            self,
            "CHECKPOINT_TOO_LARGE",
            lambda: _materialize(b"\xff" * 1048577),
        )
        samples.assert_code(
            self,
            "INVALID_CHECKPOINT_JSON",
            lambda: _materialize(b"\xff" * 1048576),
        )
        unsorted = {
            "sha256": "0" * 64,
            "schema_version": parsed["schema_version"],
            "payload": parsed["payload"],
        }
        raw = json.dumps(
            unsorted,
            ensure_ascii=False,
            sort_keys=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertNotEqual(raw, samples.canon(unsorted))
        samples.assert_code(self, "NONCANONICAL_CHECKPOINT", lambda: _materialize(raw))
        samples.assert_code(
            self,
            "CHECKPOINT_DIGEST_MISMATCH",
            lambda: _materialize(samples.canon(unsorted)),
        )
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            samples.assert_code(
                self,
                "CHECKPOINT_DIGEST_MISMATCH",
                lambda: _materialize(samples.canon(unsorted)),
            )
            self.assertEqual(actual.call_count, 0)

    def test_rehashed_semantic_damage_still_calls_f122_before_pins(self):
        parsed = json.loads(_blob())
        parsed["payload"]["bound_language"]["approved_template"]["body"] = "tampered literal"
        damaged = samples.canon(samples.envelope(parsed["payload"]))
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            with self.assertRaises(f122.TemplateMaterializationError) as caught:
                _materialize(damaged, registry="other-registry", pack="other-pack")
        self.assertEqual(caught.exception.code, "TEMPLATE_CONTENT_MISMATCH")
        self.assertIs(type(caught.exception), f122.TemplateMaterializationError)
        self.assertEqual(actual.call_count, 1)
        self.assertNotIn("tampered", str(caught.exception))

    def test_registry_pin_is_checked_before_pack_pin(self):
        blob = _blob()
        samples.assert_code(
            self,
            "CHECKPOINT_REGISTRY_MISMATCH",
            lambda: _materialize(blob, registry="other-registry", pack="other-pack"),
        )
        samples.assert_code(
            self,
            "CHECKPOINT_PACK_MISMATCH",
            lambda: _materialize(blob, registry="fixture-v1", pack="other-pack"),
        )
        for registry, pack in (
            ("", "en-v1"),
            ("-bad", "en-v1"),
            ("a" * 129, "en-v1"),
            ("has space", "en-v1"),
            ("fixture-v1", ""),
        ):
            with self.subTest(registry=registry, pack=pack):
                samples.assert_code(
                    self,
                    "INVALID_CHECKPOINT_INPUT",
                    lambda registry=registry, pack=pack: _materialize(
                        blob, registry=registry, pack=pack
                    ),
                )
        samples.assert_code(
            self,
            "CHECKPOINT_REGISTRY_MISMATCH",
            lambda: _materialize(blob, registry="a" * 128, pack="en-v1"),
        )

    def test_valid_large_text_hits_the_inclusive_byte_limit(self):
        def fitted(target):
            base_sample = samples.case("en-GB_INITIAL")["input"]
            for version in ("en-v1", "en-v1x"):
                trial = copy.deepcopy(base_sample)
                trial["loaded_registry"]["language_pack_versions"]["en-GB"] = version
                trial["loaded_registry"]["packs_by_locale"]["en-GB"]["version"] = version
                trial["bound_language"]["language_pack_version"] = version
                bodies = {}
                for length in (1, 2):
                    body = "A" * length
                    trial["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"] = body
                    trial["bound_language"]["approved_template"]["body"] = body
                    payload = {
                        "loaded_registry": trial["loaded_registry"],
                        "bound_language": trial["bound_language"],
                        "template_id": trial["template_id"],
                    }
                    bodies[length] = len(samples.canon(samples.envelope(payload)))
                step = bodies[2] - bodies[1]
                self.assertEqual(step, 2)
                if (target - bodies[1]) % step == 0 and target >= bodies[1]:
                    length = 1 + (target - bodies[1]) // step
                    body = "A" * length
                    trial["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"] = body
                    trial["bound_language"]["approved_template"]["body"] = body
                    payload = {
                        "loaded_registry": trial["loaded_registry"],
                        "bound_language": trial["bound_language"],
                        "template_id": trial["template_id"],
                    }
                    predicted = samples.canon(samples.envelope(payload))
                    self.assertEqual(len(predicted), target)
                    return trial, predicted, version
            self.fail("byte limit was not reachable with a valid body")

        exact, exact_bytes, exact_version = fitted(1048576)
        over, over_bytes, over_version = fitted(1048577)
        self.assertEqual(
            exact["loaded_registry"]["packs_by_locale"]["en-GB"]["templates"]["initial"]["body"],
            exact["bound_language"]["approved_template"]["body"],
        )
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            blob = checkpoint.capture_checkpoint(
                exact["loaded_registry"],
                exact["bound_language"],
                template_id=exact["template_id"],
            )
            self.assertEqual(len(blob), 1048576)
            self.assertEqual(blob, exact_bytes)
            restored = _materialize(blob, pack=exact_version)
            self.assertEqual(restored["body"], exact["bound_language"]["approved_template"]["body"])
            self.assertGreater(actual.call_count, 0)
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            samples.assert_code(
                self,
                "CHECKPOINT_TOO_LARGE",
                lambda: checkpoint.capture_checkpoint(
                    over["loaded_registry"],
                    over["bound_language"],
                    template_id=over["template_id"],
                ),
            )
            self.assertEqual(actual.call_count, 1)
        with mock.patch.object(
            f122, "materialize_bound_template", wraps=f122.materialize_bound_template
        ) as actual:
            samples.assert_code(
                self,
                "CHECKPOINT_TOO_LARGE",
                lambda: _materialize(over_bytes, pack=over_version),
            )
            self.assertEqual(actual.call_count, 0)

    def test_source_has_no_forbidden_operations(self):
        path = samples.PACKAGE / "source" / "sales_template_checkpoint.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed = {
            "hashlib",
            "json",
            "re",
            "sales_runtime_materialization",
            "sales_template_materialization",
        }
        forbidden_calls = {"open", "eval", "exec", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0], allowed)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_calls)
        source = path.read_text(encoding="utf-8")
        for token in ("pickle", "subprocess", "socket", "sqlite", "urllib", "os.environ"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
