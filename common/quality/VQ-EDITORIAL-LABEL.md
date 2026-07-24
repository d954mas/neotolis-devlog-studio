# VQ-EDITORIAL-LABEL

## Use when

В viewer-visible copy могут попасть служебные метки монтажа.

## Do not use for

Явно одобренную публичную сериализацию, добавленную в
`allow_editorial_labels` story contract.

## Check

Preflight сканирует видимый body text всех `data/hyperframes/*/index.html` и
блокирует `REEL 01`, `PART 2`, `VERSION 3`, `CUT 4` и русские эквиваленты.
Текст внутри `script/style/template` не считается viewer-visible.

## Evidence required

`data/review/preflight.json` без `VQ-EDITORIAL-LABEL` для exact sources.

## Not enough

Отсутствие метки в одном contact-sheet кадре не доказывает, что её нет в
другой сцене.
