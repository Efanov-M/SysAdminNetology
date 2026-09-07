# Backup And Restore

## Что можно скачать

- backup ZIP всей семьи
- JSON export всей семьи
- JSON export одного пациента
- `.ics` напоминаний

## Что входит в backup ZIP

- `family-export.json`
- загруженные документы

## Restore

Restore использует backend preview/apply flow:

1. загрузить backup
2. посмотреть preview
3. выбрать действия по конфликтам
4. применить restore

## Что важно проверить после restore

- пациенты на месте
- документы открываются
- лекарства и напоминания восстановлены
- Matrix/notification settings не потеряли рабочие значения

## Если restore пошёл не так

- сначала сохраните diagnostics bundle
- не делайте поверх этого ещё один restore вслепую
- проверьте preview-результат и audit log
