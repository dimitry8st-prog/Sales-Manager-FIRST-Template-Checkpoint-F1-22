# -*- coding: utf-8 -*-
"""Собственные тесты F1-30 R2 (дополняют публичные, не заменяют).

R2-ядро — consumer-валидация: адаптер обязан вызвать sales_rules.validate_materials
на точном выходе materialize ДО save; RuleViolation проходит исходным объектом,
callback не вызывается, тема/текст не исправляются.

Блоки:
- materialization failure с временной подменой зависимости (п.5 ТЗ);
- QUESTION с пустой темой — отказ адаптера: тот же код, что у consumer,
  zero save, inputs immutable;
- identity исходного объекта consumer-ошибки (under подмена validate
  sentinel-примером — assertIs);
- положительные на runtime_initial_{en,ru,de}.json: exact F122-выход,
  exact-ABI точность стадий (включая validate), ровно один save.
Подмены точечные (unittest.mock.patch.object), восстанавливаются.
"""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

P = Path(__file__).resolve().parents[1]

try:  # тестовый harness и так поднимает src+reference; импорт не зависит
    import sales_runtime_materialization as srm
except ImportError:  # прямой вызов файла тестов без discover
    import sys
    sys.path[:0] = [str(P / "src"), str(P / "reference")]
    import sales_runtime_materialization as srm

from sales_action_locale import bind_action_locale
from sales_template_materialization import TemplateMaterializationError, materialize_bound_template
from sales_rules import RuleViolation, validate_materials

RUNTIME_FIXTURES = ["runtime_initial_en.json", "runtime_initial_ru.json",
                    "runtime_initial_de.json"]
F122_KEYS = {"schema_version", "locale", "language_pack_version",
             "registry_version", "kind", "subject", "body", "fact_ids",
             "template_id"}


class Candidate(unittest.TestCase):
    def fixture(self, name="runtime_initial_en.json"):
        return json.loads((P / "fixtures" / name).read_text(encoding="utf-8"))

    def reference_fixture(self, name="f120_positive_en_ru.json"):
        return json.loads(
            (P / "reference/tests/fixtures/wave3/f120" / name).read_text(encoding="utf-8"))

    def args(self, f):
        return {k: f[k] for k in
                ["locale", "required_template_id", "pinned_pack_version"]}

    def call(self, f, save, **kw):
        args = self.args(f)
        args.update(kw)
        return srm.prepare_bound_materials(
            f["loaded_registry"], f["binding_config"],
            now=datetime.fromisoformat(f["now"]),
            save_materials=save, **args,
        )

    def exact(self, f):
        """Независимое ожидание: связка bind+materialize руками."""
        bound = bind_action_locale(
            f["loaded_registry"], f["binding_config"],
            now=datetime.fromisoformat(f["now"]), **self.args(f))
        return materialize_bound_template(
            f["loaded_registry"], bound, template_id=f["required_template_id"])

    def test_positive_runtime_initial_exact_en_ru_de(self):
        # Ровно один save с точным F122-выходом; validate-стадия получает
        # тот же словарь; результат callback и входы без изменений.
        for name in RUNTIME_FIXTURES:
            with self.subTest(name=name):
                f = self.fixture(name)
                before = copy.deepcopy(f)
                expected = self.exact(f)
                self.assertEqual(set(expected), F122_KEYS)
                self.assertEqual(expected["schema_version"],
                                 "FIRST_TEMPLATE_MATERIALS_V1")
                validate_calls = []
                real_validate = srm.validate_materials

                def spy_validate(materials):
                    validate_calls.append(materials)
                    return real_validate(materials)

                calls = []
                sentinel = object()
                with mock.patch.object(srm, "validate_materials", spy_validate):
                    result = self.call(f, lambda x: (calls.append(x), sentinel)[1])
                self.assertIs(result, sentinel)
                self.assertEqual(calls, [expected])
                self.assertEqual(validate_calls, [expected])
                self.assertIs(validate_calls[0], calls[0])
                self.assertEqual(f, before)

    def test_question_blank_subject_zero_save_same_code(self):
        # QUESTION/explain с пустой темой: F120/F122 проходят, consumer
        # отвергает — адаптер обязан выдать исходную RuleViolation
        # (MISSING_SUBJECT) и НЕ вызвать callback ни разу; никаких
        # надстроек темы.
        f = self.reference_fixture("f120_positive_en_ru.json")
        before = copy.deepcopy(f)
        calls = []
        with self.assertRaises(RuleViolation) as caught:
            self.call(f, calls.append)
        self.assertEqual(str(caught.exception), "MISSING_SUBJECT")
        self.assertEqual(calls, [])
        self.assertEqual(f, before)

    def test_validate_error_identity_passes_through_unwrapped(self):
        # Identity ошибки consumer: объект, возбуждённый validate_materials,
        # проходит наружу тем же самым экземпляром (адаптер не оборачивает).
        f = self.fixture()
        sentinel_error = RuleViolation("MISSING_SUBJECT")
        calls = []
        with mock.patch.object(srm, "validate_materials",
                               side_effect=sentinel_error):
            with self.assertRaises(RuleViolation) as caught:
                self.call(f, calls.append)
        self.assertIs(caught.exception, sentinel_error)
        self.assertEqual(calls, [])

    def test_materialize_failure_zero_save_original_error(self):
        # Отказ materialize: исходное исключение, callback ни разу не вызван,
        # validate-стадия не достигнута.
        error = TemplateMaterializationError("TEMPLATE_CONTENT_MISMATCH")
        f = self.fixture()
        validate_calls = []
        calls = []
        with mock.patch.object(srm, "materialize_bound_template", side_effect=error), \
             mock.patch.object(srm, "validate_materials",
                               side_effect=lambda m: validate_calls.append(m)):
            with self.assertRaises(TemplateMaterializationError) as caught:
                self.call(f, calls.append)
        self.assertIs(caught.exception, error)
        self.assertEqual(str(caught.exception), "TEMPLATE_CONTENT_MISMATCH")
        self.assertEqual(calls, [])
        self.assertEqual(validate_calls, [])

    def test_bind_materialize_validate_exact_abi_inputs(self):
        # Точность ABI всех трёх стадий: bind получает точные
        # now/locale/required/pinned; materialize — тот же объект
        # loaded_registry и шаблон в статусе BOUND; validate — точный
        # F122-дикт; save — тот же словарь.
        f = self.fixture()
        now = datetime.fromisoformat(f["now"])
        calls = {}
        real_bind = srm.bind_action_locale
        real_mat = srm.materialize_bound_template
        real_validate = srm.validate_materials

        def spy_bind(reg, cfg, **kw):
            calls["bind"] = {"registry": reg, "config": cfg, "kw": kw}
            return real_bind(reg, cfg, **kw)

        def spy_mat(reg, bound, *, template_id):
            calls["mat"] = {"registry": reg, "bound": bound,
                            "template_id": template_id}
            return real_mat(reg, bound, template_id=template_id)

        def spy_validate(materials):
            calls["validate"] = materials
            return real_validate(materials)

        def save(x):
            calls["save"] = x

        with mock.patch.object(srm, "bind_action_locale", spy_bind), \
             mock.patch.object(srm, "materialize_bound_template", spy_mat), \
             mock.patch.object(srm, "validate_materials", spy_validate):
            self.call(f, save)
        b = calls["bind"]
        self.assertIs(b["registry"], f["loaded_registry"])
        self.assertIs(b["config"], f["binding_config"])
        self.assertEqual(b["kw"], {"now": now, "locale": f["locale"],
                                   "required_template_id": f["required_template_id"],
                                   "pinned_pack_version": f["pinned_pack_version"]})
        m = calls["mat"]
        self.assertIs(m["registry"], f["loaded_registry"])
        self.assertEqual(m["template_id"], f["required_template_id"])
        self.assertEqual(m["bound"]["schema_version"], "FIRST_ACTION_LANGUAGE_V1")
        self.assertEqual(m["bound"]["status"], "BOUND")
        self.assertEqual(m["bound"]["locale"], f["locale"])
        # validate и save получают один и тот же объект F122-словаря.
        self.assertIs(calls["validate"], calls["save"])
        self.assertEqual(set(calls["save"]), F122_KEYS)

    def test_save_gets_original_dict_not_validate_return(self):
        # «Не дописывать/не нормализовать»: в save уходит исходный F122-dict,
        # даже если validate вернул значение (стрип-subject) — оно игнорируется.
        f = self.fixture()
        expected = self.exact(f)
        calls = []

        def fake_return(materials):
            validate_materials(materials)
            return "DECOY-STRIPPED-SUBJECT"

        with mock.patch.object(srm, "validate_materials", fake_return):
            self.call(f, calls.append)
        self.assertEqual(calls, [expected])
        self.assertEqual(calls[0]["subject"], expected["subject"])

    def test_pinned_drift_rejection_zero_save_inputs_immutable(self):
        # Drift закреплённой версии: исходное исключение, zero save,
        # входы не изменены (уход ДО validate-стадии).
        for name in RUNTIME_FIXTURES:
            with self.subTest(name=name):
                f = self.fixture(name)
                f["pinned_pack_version"] = {"en": "en-v2", "ru": "ru-v2",
                                            "de": "de-v2"}[name.replace(
                    "runtime_initial_", "").replace(".json", "")]
                before = copy.deepcopy(f)
                calls = []
                with self.assertRaises(ValueError) as caught:
                    self.call(f, calls.append)
                self.assertEqual(str(caught.exception), "PACK_VERSION_CHANGED")
                self.assertEqual(calls, [])
                self.assertEqual(f, before)

    def test_subject_passes_byte_exact_when_dependency_yields_spaced(self):
        # Против «нормализации пробелов»: если зависимость выдала subject
        # с боковыми пробелами, адаптер обязан передать его как есть —
        # без strip-правки самой зависимости и без вмешательства.
        f = self.fixture()
        expected = self.exact(f)
        injected = copy.deepcopy(expected)
        injected["subject"] = "  spaced  "
        calls = []
        with mock.patch.object(srm, "materialize_bound_template",
                               side_effect=lambda reg, bound, *, template_id: injected):
            self.call(f, calls.append)
        self.assertEqual(calls, [injected])
        self.assertIs(calls[0], injected)
        self.assertEqual(calls[0]["subject"], "  spaced  ")

    def test_callback_exception_identity_after_materialize(self):
        # Callback-ошибка после материализации и валидации: исходный объект,
        # ровно один вызов.
        f = self.fixture("runtime_initial_ru.json")
        error = RuntimeError("synthetic-callback")
        calls = []

        def fail(x):
            calls.append(x)
            raise error

        with self.assertRaises(RuntimeError) as caught:
            self.call(f, fail)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()