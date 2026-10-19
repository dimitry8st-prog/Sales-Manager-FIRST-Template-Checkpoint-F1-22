# -*- coding: utf-8 -*-
"""F1-30 — адаптер точного одобренного языкового шаблона перед сохранением
материалов FIRST (замороженный контракт — CONTRACT.json, revision R2).

Единственная функция ``prepare_bound_materials`` — чистая композиция трёх
принятых компонентов и consumer-валидации, без собственных правил:

1. ``bind_action_locale`` (F1-20) — привязка локали к действию с точными
   входами ABI; исходные ошибки зависимостей проходят как есть.
2. ``materialize_bound_template`` (F122) — точная материализация связанного
   шаблона по тому же ``loaded_registry`` и выбранному template ID; выход
   FIRST_TEMPLATE_MATERIALS_V1 — "материалы", без добавленных полей.
3. ``validate_materials`` (sales_rules) — consumer-валидация точного
   F122-словаря ДО любого сохранения; пустая тема/текст (в т.ч. только из
   пробелов) для consumer непригодны — `RuleViolation` проходит исходным
   объектом, callback не вызывается. Тема и текст никогда не исправляются
   и не дополняются.
4. ``save_materials(materials)`` — вызывается ровно один раз, материалы —
   единственный позиционный аргумент (без слияния, нормализации пробелов,
   перевода и агентского текста); результат callback возвращается как есть.

Ошибки зависимостей, consumer-валидации и callback пропускаются исходными
исключениями; на любом отказе callback не вызывается вовсе (zero save).
Никакого fallback, повторного сохранения, изменения входов и разрешений
отправки; I/O в модуле отсутствует (кроме переданного save-callback),
внешний ``SEND_READY`` не выдаётся.
"""
from sales_action_locale import bind_action_locale
from sales_template_materialization import materialize_bound_template
from sales_rules import validate_materials


def prepare_bound_materials(loaded_registry, binding_config, *, now, locale,
                            required_template_id, pinned_pack_version,
                            save_materials):
    """Связать шаблон с языком, материализовать, провалидировать и
    сохранить как есть.

    Последовательность и правила — докстринг модуля; контракт ошибок:
    исключения обеих зависимостей, consumer-валидации (``RuleViolation``)
    и save-callback проходят исходными объектами, callback не вызывается
    на любом отказе до него.
    """
    bound_language = bind_action_locale(
        loaded_registry,
        binding_config,
        now=now,
        locale=locale,
        required_template_id=required_template_id,
        pinned_pack_version=pinned_pack_version,
    )
    materials = materialize_bound_template(
        loaded_registry,
        bound_language,
        template_id=required_template_id,
    )
    validate_materials(materials)
    return save_materials(materials)