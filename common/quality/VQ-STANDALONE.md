# VQ-STANDALONE

## Use when

Любой reel/short должен быть понятен без предыдущего ролика.

## Do not use for

Внутренние regression-рендеры и отдельные beats, которые не публикуются.

## Check

До storyboard существует `data/plan/story_contract.json` с тремя непустыми
полями: `premise`, `causal_turn`, `payoff`. Для vertical production это
mechanical preflight error, а не reviewer suggestion.

## Evidence required

`data/review/preflight.json` без `VQ-STANDALONE` и story contract, который
reviewer может пересказать как законченную историю без sibling reel.

## Not enough

Номер серии, маленькое название игры или фраза «теперь/а ещё» не заменяют
самостоятельный premise.
