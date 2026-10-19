# F1-22 R2 — отдельная ветка проверенного возврата

Эта ветка `feat/f1-22-checkpoint-r2-workspace` публикует возврат, собранный и проверенный в рабочей папке. Ветка `feat/f1-22-checkpoint-r2` не изменялась.

## Возврат

- [F1-22_R2_RETURN_R1.zip](artifacts/F1-22_R2_RETURN_R1.zip?raw=true) — один корень `F1-22_Dmitriy_Stazher_R2`, 87 файлов.
- Пакет в репозитории: [F1-22_Dmitriy_Stazher_R2](F1-22_Dmitriy_Stazher_R2).
- Исходный выданный архив в корне репозитория сохранён как был.

SHA-256 этого ZIP:

```text
66a30a5e66dc8114e8350b96ca67e4132ce75ae329b61bcf524f32bd8a39692b
```

## Что реализовано

`source/sales_template_checkpoint.py` фиксирует уже выбранный шаблон в канонических байтах и перед внешним save сравнивает checkpoint с текущим результатом F130. Digest проверяет целостность байтов и не даёт разрешение на отправку. Принятый `materialize_bound_template` не менялся.

## Фактические проверки

Среда: Python 3.12.8, стандартная библиотека. Пропусков не было.

| Проверка | Результат | Код |
| --- | --- | --- |
| Scaffold `CHECK_PACKAGE.py` | 59 защищённых файлов | 0 |
| Scaffold `baseline` | 152 PASS | 0 |
| Scaffold `candidate` | `MISSING_IMPLEMENTATION` | 3 |
| Чистая копия `CHECK_PACKAGE.py` | 59 защищённых файлов | 0 |
| Чистая копия `baseline` | 152 PASS | 0 |
| Чистая копия `candidate` | 13, failures 0, errors 0, skips 0 | 0 |
| Чистая копия `own` | 27, failures 0, errors 0, skips 0 | 0 |

Готовый ZIP проверен отдельно: CRC, один корень, состав по `RETURN_MANIFEST.json`, защищённые байты и совпадение реализации с проверенным файлом.

Исходный `F1-22_Dmitriy_Stazher_R2.zip` в рабочей папке не найден. Чистый прогон собран из побайтовой копии каталога до правок. Установка в SOURCE, production, tenant/campaign/principal и приёмка заказчиком — `NOT_RUN`.
