"""Exact, side-effect-free materialization of a previously bound FIRST template.

F122 validates the relationship between a frozen F120 bound object and the
actually loaded F106 registry. It deliberately does not select a locale or
perform any message delivery.
"""
from __future__ import annotations

import copy
import re

from sales_language_registry import (
    LanguageRegistryError,
    build_policy_language_fields,
    validate_language_pack,
)


class TemplateMaterializationError(ValueError):
    """A safe, machine-readable F122 validation error.

    ``code`` contains the error code only and ``str(exc) == exc.code``. Input
    content is never included in the exception message.
    """

    def __init__(self, code: str):
        super().__init__(code)

    @property
    def code(self) -> str:
        return self.args[0]

    def __str__(self) -> str:
        return self.code


_BOUND_KEYS = {
    "schema_version",
    "status",
    "locale",
    "language_pack_version",
    "registry_version",
    "approved_template",
    "approved_fact_ids",
}
_TEMPLATE_KEYS = {"kind", "locale", "subject", "body", "fact_ids"}
_LOADED_KEYS = {
    "schema_version",
    "registry_version",
    "default_locale",
    "active_locales",
    "language_pack_versions",
    "approved_fact_ids",
    "packs_by_locale",
}
_PACK_KEYS = {"schema_version", "locale", "version", "templates"}
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _raise(code: str) -> None:
    raise TemplateMaterializationError(code)


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER_RE.fullmatch(value) is not None


def _same_keys_exact(mapping: object, expected: set[str]) -> bool:
    return (
        type(mapping) is dict
        and set(mapping.keys()) == expected
        and all(type(key) is str for key in mapping.keys())
    )


def _strict_loaded_tree(loaded: dict) -> None:
    """Reject builtin subclasses only after F106 has accepted the whole tree.

    The traversal preserves the field/error categories and ordering recorded in
    CONTRACT.json: facts, schema, identifiers, locales, active-order packs,
    then each pack's templates in insertion order.
    """
    # F106's approved-fact validation runs before its schema validation.
    fact_ids = loaded["approved_fact_ids"]
    if type(fact_ids) is not list or any(type(item) is not str for item in fact_ids):
        _raise("INVALID_FACT_SET")

    # Root and mapping containers / schema fields.
    if not _same_keys_exact(loaded, _LOADED_KEYS):
        _raise("INVALID_SCHEMA")
    if type(loaded["schema_version"]) is not str or loaded["schema_version"] != "FIRST_LANGUAGE_REGISTRY_LOADED_V1":
        _raise("INVALID_SCHEMA")
    if type(loaded["language_pack_versions"]) is not dict:
        _raise("INVALID_SCHEMA")
    if type(loaded["packs_by_locale"]) is not dict:
        _raise("INVALID_SCHEMA")

    # Identifier checks precede locale checks, matching F106's loaded order.
    if not _identifier(loaded["registry_version"]):
        _raise("INVALID_IDENTIFIER")
    versions = loaded["language_pack_versions"]
    for version in versions.values():
        if not _identifier(version):
            _raise("INVALID_IDENTIFIER")

    # Strict builtin locale strings and containers.
    if type(loaded["default_locale"]) is not str:
        _raise("INVALID_LOCALE")
    active = loaded["active_locales"]
    if type(active) is not list or any(type(locale) is not str for locale in active):
        _raise("INVALID_LOCALE")
    if any(type(locale) is not str for locale in versions.keys()):
        _raise("INVALID_LOCALE")
    packs_by_locale = loaded["packs_by_locale"]
    if any(type(locale) is not str for locale in packs_by_locale.keys()):
        _raise("INVALID_LOCALE")

    # Revisit packs in active_locales order, as F106 does.
    for locale in active:
        pack = packs_by_locale[locale]
        if not _same_keys_exact(pack, _PACK_KEYS):
            _raise("INVALID_SCHEMA")
        if type(pack["schema_version"]) is not str or pack["schema_version"] != "FIRST_LANGUAGE_PACK_V1":
            _raise("INVALID_SCHEMA")
        if not _identifier(pack["version"]):
            _raise("INVALID_IDENTIFIER")
        if type(pack["locale"]) is not str:
            _raise("INVALID_LOCALE")
        templates = pack["templates"]
        if type(templates) is not dict:
            _raise("INVALID_SCHEMA")

        # Template key and template field order is significant for error
        # precedence, especially if several invalid templates are present.
        for template_id, template in templates.items():
            if not _identifier(template_id):
                _raise("INVALID_IDENTIFIER")
            if not _same_keys_exact(template, _TEMPLATE_KEYS):
                _raise("INVALID_SCHEMA")
            if type(template["kind"]) is not str:
                _raise("INVALID_TEMPLATE")
            if type(template["locale"]) is not str:
                _raise("TEMPLATE_LOCALE_MISMATCH")
            if type(template["subject"]) is not str:
                _raise("INVALID_TEMPLATE")
            if type(template["body"]) is not str:
                _raise("INVALID_TEMPLATE")
            template_facts = template["fact_ids"]
            if type(template_facts) is not list or any(type(item) is not str for item in template_facts):
                _raise("INVALID_TEMPLATE")


def _strict_bound_template(bound: dict) -> None:
    """Perform F122's post-F106 exact-builtin checks for the frozen bound."""
    fact_ids = bound["approved_fact_ids"]
    if type(fact_ids) is not list or any(type(item) is not str for item in fact_ids):
        _raise("INVALID_FACT_SET")

    template = bound["approved_template"]
    if not _same_keys_exact(template, _TEMPLATE_KEYS):
        _raise("INVALID_SCHEMA")
    if type(template["kind"]) is not str:
        _raise("INVALID_TEMPLATE")
    if type(template["locale"]) is not str:
        _raise("TEMPLATE_LOCALE_MISMATCH")
    if type(template["subject"]) is not str:
        _raise("INVALID_TEMPLATE")
    if type(template["body"]) is not str:
        _raise("INVALID_TEMPLATE")
    template_facts = template["fact_ids"]
    if type(template_facts) is not list or any(type(item) is not str for item in template_facts):
        _raise("INVALID_TEMPLATE")


def _preserve_f106_error(callable_, *args, **kwargs):
    """Invoke a public F106 API and preserve its machine-readable error code."""
    try:
        return callable_(*args, **kwargs)
    except LanguageRegistryError as exc:
        raise TemplateMaterializationError(exc.code) from None


def materialize_bound_template(
    loaded_registry: dict,
    bound_language: dict,
    *,
    template_id: str,
) -> dict:
    """Validate and return exact text for the already selected bound template.

    Validation order is normative and follows stages 1-11 in CONTRACT.json.
    Inputs are never modified, external effects are not performed, and all
    mutable output data is detached from the inputs.
    """
    # Stage 1: exact argument container types; inspect no fields before this.
    if type(loaded_registry) is not dict or type(bound_language) is not dict:
        _raise("INVALID_INPUT")

    # Stage 2: frozen F120 shape and required header values.
    if not _same_keys_exact(bound_language, _BOUND_KEYS):
        _raise("INVALID_SCHEMA")
    if bound_language["schema_version"] != "FIRST_ACTION_LANGUAGE_V1" or bound_language["status"] != "BOUND":
        _raise("INVALID_SCHEMA")
    if (
        type(bound_language["locale"]) is not str
        or type(bound_language["language_pack_version"]) is not str
        or type(bound_language["registry_version"]) is not str
    ):
        _raise("INVALID_SCHEMA")

    # Stage 3: validate identifiers in the exact prescribed order.
    if not _identifier(template_id):
        _raise("INVALID_IDENTIFIER")
    if not _identifier(bound_language["language_pack_version"]):
        _raise("INVALID_IDENTIFIER")
    if not _identifier(bound_language["registry_version"]):
        _raise("INVALID_IDENTIFIER")

    # Stage 4: actual F106 full-tree validation always precedes F122's strict
    # builtin-subclass pass and all bound-vs-registry business comparisons.
    _preserve_f106_error(
        build_policy_language_fields,
        loaded_registry,
        locale=bound_language["locale"],
    )
    _strict_loaded_tree(loaded_registry)

    # Stage 5: actual F106 validates the bound template in a one-template pack
    # before any version, ID, scope, or content comparison is performed.
    ephemeral_pack = {
        "schema_version": "FIRST_LANGUAGE_PACK_V1",
        "locale": bound_language["locale"],
        "version": bound_language["language_pack_version"],
        "templates": {template_id: bound_language["approved_template"]},
    }
    _preserve_f106_error(
        validate_language_pack,
        ephemeral_pack,
        approved_fact_ids=bound_language["approved_fact_ids"],
    )
    _strict_bound_template(bound_language)

    # Stage 6: the bound version must match both independent loaded values.
    locale = bound_language["locale"]
    selected_pack = loaded_registry["packs_by_locale"][locale]
    bound_version = bound_language["language_pack_version"]
    if (
        bound_version != loaded_registry["language_pack_versions"][locale]
        or bound_version != selected_pack["version"]
    ):
        _raise("PACK_VERSION_CHANGED")

    # Stage 7: registry version must match exactly.
    if bound_language["registry_version"] != loaded_registry["registry_version"]:
        _raise("REGISTRY_VERSION_CHANGED")

    # Stage 8: the exact selected template ID must exist in the selected pack.
    templates = selected_pack["templates"]
    if template_id not in templates:
        _raise("TEMPLATE_NOT_FOUND")

    # Stage 9: exact dict equality checks literal text, whitespace and list order.
    if templates[template_id] != bound_language["approved_template"]:
        _raise("TEMPLATE_CONTENT_MISMATCH")

    # Stage 10: a valid bound scope must not exceed the actually loaded scope.
    loaded_facts = set(loaded_registry["approved_fact_ids"])
    if not set(bound_language["approved_fact_ids"]).issubset(loaded_facts):
        _raise("FACT_SCOPE_MISMATCH")

    # Stage 11: exact nine-field result; fact_ids is an independent deep copy.
    approved_template = bound_language["approved_template"]
    return {
        "schema_version": "FIRST_TEMPLATE_MATERIALS_V1",
        "locale": locale,
        "language_pack_version": bound_version,
        "registry_version": bound_language["registry_version"],
        "kind": approved_template["kind"],
        "subject": approved_template["subject"],
        "body": approved_template["body"],
        "fact_ids": copy.deepcopy(approved_template["fact_ids"]),
        "template_id": template_id,
    }
