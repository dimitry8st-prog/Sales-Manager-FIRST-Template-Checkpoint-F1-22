"""F1-22 R2: deterministic template snapshots and the existing F130 save seam.

The codec checks transport integrity, never origin or sending permission.
F122 owns frozen template semantics; F130 owns current policy validation.
No I/O, time lookup, retries or state are introduced by this module.
"""
import hashlib
import json
import re

import sales_runtime_materialization as _runtime
import sales_template_materialization as _templates


_SCHEMA = "FIRST_TEMPLATE_CHECKPOINT_V1"
_MAX_BYTES = 1048576
_MAX_DEPTH = 64
_PAYLOAD_KEYS = {"loaded_registry", "bound_language", "template_id"}
_ENVELOPE_KEYS = {"schema_version", "payload", "sha256"}
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class TemplateCheckpointError(ValueError):
    """A contract error carrying only a safe, fixed machine-readable code."""

    @property
    def code(self):
        return self.args[0]

    def __str__(self):
        return self.code


class _InvalidJSON(ValueError):
    """Internal parser signal; never exposes input values in public errors."""


def _fail(code):
    raise TemplateCheckpointError(code)


def _check_string(value, code):
    if type(value) is not str or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        _fail(code)


def _check_domain(value, code):
    """Only exact dict/list/str; container root=1; aliases are not cycles.

    The active path, rather than all visited objects, distinguishes shared
    references from cycles. At most 64 nested containers can be traversed.
    """
    active = set()

    def visit(item, depth):
        kind = type(item)
        if kind is str:
            _check_string(item, code)
            return
        if kind not in (dict, list) or depth > _MAX_DEPTH:
            _fail(code)
        identity = id(item)
        if identity in active:
            _fail(code)
        active.add(identity)
        try:
            if kind is dict:
                for key, child in item.items():
                    _check_string(key, code)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
        finally:
            active.remove(identity)

    visit(value, 1)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJSON()
        result[key] = value
    return result


def _reject_number(_literal):
    # All numbers, including finite values, are outside the transport domain.
    raise _InvalidJSON()


def _parse(blob):
    try:
        text = blob.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            raise _InvalidJSON()
        envelope = json.loads(
            text, object_pairs_hook=_unique_object,
            parse_int=_reject_number, parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeError, ValueError, RecursionError):
        _fail("INVALID_CHECKPOINT_JSON")

    # The envelope is transport wrapping, not an additional payload level.
    # Its other fields still receive their own safe-domain validation.
    if type(envelope) is dict:
        for key, value in envelope.items():
            _check_string(key, "INVALID_CHECKPOINT_JSON")
            _check_domain(value, "INVALID_CHECKPOINT_JSON")
    else:
        _check_domain(envelope, "INVALID_CHECKPOINT_JSON")
    return envelope


def _check_schema(envelope):
    if type(envelope) is not dict or set(envelope) != _ENVELOPE_KEYS:
        _fail("INVALID_CHECKPOINT_SCHEMA")
    if (
        envelope["schema_version"] != _SCHEMA
        or type(envelope["sha256"]) is not str
        or _DIGEST_RE.fullmatch(envelope["sha256"]) is None
    ):
        _fail("INVALID_CHECKPOINT_SCHEMA")
    payload = envelope["payload"]
    if (
        type(payload) is not dict
        or set(payload) != _PAYLOAD_KEYS
        or type(payload["loaded_registry"]) is not dict
        or type(payload["bound_language"]) is not dict
        or type(payload["template_id"]) is not str
    ):
        _fail("INVALID_CHECKPOINT_SCHEMA")


def capture_checkpoint(loaded_registry, bound_language, *, template_id):
    """Validate via real F122, then encode a canonical self-contained snapshot."""
    if (
        type(loaded_registry) is not dict
        or type(bound_language) is not dict
        or type(template_id) is not str
    ):
        _fail("INVALID_CHECKPOINT_INPUT")
    payload = {
        "loaded_registry": loaded_registry,
        "bound_language": bound_language,
        "template_id": template_id,
    }
    _check_domain(payload, "INVALID_CHECKPOINT_INPUT")
    _templates.materialize_bound_template(
        loaded_registry, bound_language, template_id=template_id,
    )
    envelope = {
        "schema_version": _SCHEMA,
        "payload": payload,
        "sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
    }
    blob = _canonical(envelope)
    if len(blob) > _MAX_BYTES:
        _fail("CHECKPOINT_TOO_LARGE")
    return blob


def materialize_checkpoint(blob, *, expected_registry_version, expected_pack_version):
    """Decode in contract order and return the actual F122 result unchanged."""
    if type(blob) is not bytes or any(
        type(version) is not str or _VERSION_RE.fullmatch(version) is None
        for version in (expected_registry_version, expected_pack_version)
    ):
        _fail("INVALID_CHECKPOINT_INPUT")
    if len(blob) > _MAX_BYTES:
        _fail("CHECKPOINT_TOO_LARGE")
    envelope = _parse(blob)
    _check_schema(envelope)
    if blob != _canonical(envelope):
        _fail("NONCANONICAL_CHECKPOINT")
    payload = envelope["payload"]
    if hashlib.sha256(_canonical(payload)).hexdigest() != envelope["sha256"]:
        _fail("CHECKPOINT_DIGEST_MISMATCH")
    material = _templates.materialize_bound_template(
        payload["loaded_registry"], payload["bound_language"],
        template_id=payload["template_id"],
    )
    if material["registry_version"] != expected_registry_version:
        _fail("CHECKPOINT_REGISTRY_MISMATCH")
    if material["language_pack_version"] != expected_pack_version:
        _fail("CHECKPOINT_PACK_MISMATCH")
    return material


def prepare_checkpoint_materials(blob, loaded_registry, binding_config, *, now,
                                locale, required_template_id, pinned_pack_version,
                                save_materials):
    """Use real F130 first; compare the snapshot inside its single-save seam."""
    if not callable(save_materials):
        _fail("INVALID_CHECKPOINT_INPUT")

    def checked_save(materials):
        frozen = materialize_checkpoint(
            blob,
            expected_registry_version=materials["registry_version"],
            expected_pack_version=materials["language_pack_version"],
        )
        if frozen != materials:
            _fail("CHECKPOINT_MATERIALS_MISMATCH")
        return save_materials(materials)

    return _runtime.prepare_bound_materials(
        loaded_registry, binding_config, now=now, locale=locale,
        required_template_id=required_template_id,
        pinned_pack_version=pinned_pack_version, save_materials=checked_save,
    )
