"""F1-22 R2 — переносимый checkpoint уже выбранного шаблона.

Фиксирует loaded registry, связанный шаблон и template_id в канонических
байтах и сверяет их с текущим результатом F130 непосредственно перед
внешним save. Digest — контроль целостности канонической формы, не подпись
и не разрешение на отправку. Текущую привязку проверяет неизменённый F130.
"""
import hashlib
import json
import re

import sales_runtime_materialization
import sales_template_materialization


class TemplateCheckpointError(ValueError):
    """Ошибка транспортного контракта. Текст — только машинный код."""

    def __init__(self, code):
        super().__init__(code)

    @property
    def code(self):
        return self.args[0]

    def __str__(self):
        return self.args[0]


_SCHEMA_VERSION = "FIRST_TEMPLATE_CHECKPOINT_V1"
_MAX_BLOB_BYTES = 1048576
_MAX_CONTAINER_DEPTH = 64
_ENVELOPE_KEYS = {"schema_version", "payload", "sha256"}
_PAYLOAD_KEYS = {"loaded_registry", "bound_language", "template_id"}
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_LEADING_JSON_WS = re.compile(r"[ \t\r\n]*")


class _JsonReject(Exception):
    """Нарушение strict JSON: дубликат ключа или NaN/Infinity."""


class _DomainError(Exception):
    """Запрещённый domain, surrogate, цикл или глубина контейнеров."""


def _fail(code):
    raise TemplateCheckpointError(code)


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _has_surrogate(text):
    return any(0xD800 <= ord(character) <= 0xDFFF for character in text)


def _walk(value, depth, stack, done):
    kind = type(value)
    if kind is str:
        if _has_surrogate(value):
            raise _DomainError()
        return
    if kind is not dict and kind is not list:
        raise _DomainError()
    if depth > _MAX_CONTAINER_DEPTH:
        raise _DomainError()
    marker = id(value)
    if marker in stack:
        raise _DomainError()
    if marker in done:
        return
    stack.add(marker)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str or _has_surrogate(key):
                raise _DomainError()
            _walk(item, depth + 1, stack, done)
    else:
        for item in value:
            _walk(item, depth + 1, stack, done)
    stack.remove(marker)
    done.add(marker)


def _payload_domain(payload):
    _walk(payload, 1, set(), set())


def _reject_constant(_token):
    raise _JsonReject()


def _pairs(pairs):
    seen = set()
    mapping = {}
    for key, item in pairs:
        if key in seen:
            raise _JsonReject()
        seen.add(key)
        mapping[key] = item
    return mapping


def _decode_json(blob):
    if (
        blob.startswith(b"\xef\xbb\xbf")
        or blob.startswith(b"\xff\xfe")
        or blob.startswith(b"\xfe\xff")
    ):
        _fail("INVALID_CHECKPOINT_JSON")
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        _fail("INVALID_CHECKPOINT_JSON")
    if text.startswith("\ufeff"):
        _fail("INVALID_CHECKPOINT_JSON")
    decoder = json.JSONDecoder(
        object_pairs_hook=_pairs,
        parse_constant=_reject_constant,
    )
    start = _LEADING_JSON_WS.match(text).end()
    try:
        value, end = decoder.raw_decode(text, start)
    except (_JsonReject, json.JSONDecodeError, ValueError):
        _fail("INVALID_CHECKPOINT_JSON")
    if end != len(text):
        _fail("INVALID_CHECKPOINT_JSON")
    return value


def _decoded_domain(root):
    """Глубина payload считается с 1; оболочка envelope уровень не добавляет."""
    stack = set()
    done = set()
    if type(root) is dict:
        marker = id(root)
        stack.add(marker)
        for key, item in root.items():
            if type(key) is not str or _has_surrogate(key):
                raise _DomainError()
            _walk(item, 1, stack, done)
        stack.remove(marker)
        done.add(marker)
        return
    _walk(root, 1, stack, done)


def _require_schema(envelope):
    if type(envelope) is not dict or set(envelope) != _ENVELOPE_KEYS:
        _fail("INVALID_CHECKPOINT_SCHEMA")
    if envelope["schema_version"] != _SCHEMA_VERSION:
        _fail("INVALID_CHECKPOINT_SCHEMA")
    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
        _fail("INVALID_CHECKPOINT_SCHEMA")
    if (
        type(payload["loaded_registry"]) is not dict
        or type(payload["bound_language"]) is not dict
        or type(payload["template_id"]) is not str
    ):
        _fail("INVALID_CHECKPOINT_SCHEMA")
    digest = envelope["sha256"]
    if type(digest) is not str or _DIGEST_RE.fullmatch(digest) is None:
        _fail("INVALID_CHECKPOINT_SCHEMA")


def _version(value):
    return type(value) is str and _VERSION_RE.fullmatch(value) is not None


def capture_checkpoint(loaded_registry, bound_language, *, template_id):
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
    try:
        _payload_domain(payload)
    except _DomainError:
        _fail("INVALID_CHECKPOINT_INPUT")
    sales_template_materialization.materialize_bound_template(
        loaded_registry,
        bound_language,
        template_id=template_id,
    )
    envelope = {
        "schema_version": _SCHEMA_VERSION,
        "payload": payload,
        "sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
    }
    blob = _canonical(envelope)
    if len(blob) > _MAX_BLOB_BYTES:
        _fail("CHECKPOINT_TOO_LARGE")
    return blob


def materialize_checkpoint(blob, *, expected_registry_version, expected_pack_version):
    if type(blob) is not bytes or not _version(expected_registry_version) or not _version(expected_pack_version):
        _fail("INVALID_CHECKPOINT_INPUT")
    if len(blob) > _MAX_BLOB_BYTES:
        _fail("CHECKPOINT_TOO_LARGE")
    try:
        envelope = _decode_json(blob)
        _decoded_domain(envelope)
    except _DomainError:
        _fail("INVALID_CHECKPOINT_JSON")
    _require_schema(envelope)
    if blob != _canonical(envelope):
        _fail("NONCANONICAL_CHECKPOINT")
    payload = envelope["payload"]
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    if envelope["sha256"] != digest:
        _fail("CHECKPOINT_DIGEST_MISMATCH")
    result = sales_template_materialization.materialize_bound_template(
        payload["loaded_registry"],
        payload["bound_language"],
        template_id=payload["template_id"],
    )
    if result["registry_version"] != expected_registry_version:
        _fail("CHECKPOINT_REGISTRY_MISMATCH")
    if result["language_pack_version"] != expected_pack_version:
        _fail("CHECKPOINT_PACK_MISMATCH")
    return result


def prepare_checkpoint_materials(
    blob,
    loaded_registry,
    binding_config,
    *,
    now,
    locale,
    required_template_id,
    pinned_pack_version,
    save_materials,
):
    if not callable(save_materials):
        _fail("INVALID_CHECKPOINT_INPUT")

    def _consume(materials):
        frozen = materialize_checkpoint(
            blob,
            expected_registry_version=materials["registry_version"],
            expected_pack_version=materials["language_pack_version"],
        )
        if frozen != materials:
            _fail("CHECKPOINT_MATERIALS_MISMATCH")
        return save_materials(materials)

    return sales_runtime_materialization.prepare_bound_materials(
        loaded_registry,
        binding_config,
        now=now,
        locale=locale,
        required_template_id=required_template_id,
        pinned_pack_version=pinned_pack_version,
        save_materials=_consume,
    )
