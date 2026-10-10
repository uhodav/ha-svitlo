[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner-direct-single.svg)](https://stand-with-ukraine.pp.ua)
[![Made in Ukraine](https://img.shields.io/badge/made_in-Ukraine-ffd700.svg?labelColor=0057b7)](https://stand-with-ukraine.pp.ua)
[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/StandWithUkraine.svg)](https://stand-with-ukraine.pp.ua)
[![Russian Warship Go Fuck Yourself](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/RussianWarship.svg)](https://stand-with-ukraine.pp.ua)
[![hacs][hacs-image]][hacs-url]

# 💡 Svitlo Kyiv

A [Home Assistant][home-assistant] integration that tracks electricity outage schedules **of Kyiv** (DTEK Kyiv grids), providing outage calendars, countdown timers, and status updates.

> **Only Kyiv.** Other regions and the DTEK Kyiv Oblast provider were removed. For other regions use the origin project.
>
> **Renamed:** the integration domain is `svitlo_kyiv` (was `svitlo`). See [Upgrade from «Svitlo» (svitlo)](#upgrade-from-svitlo-svitlo).

Origin project https://github.com/ALERTua/ha-svitlo-yeah

## Data sources

The integration asks two sources at every update and takes the latest schedule of each day:

| Source | What it gives |
|---|---|
| [Yasno API](https://static.yasno.ua/kyiv/outages) | Schedule for today and tomorrow, the emergency shutdowns flag |
| [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua/blob/main/data/kyiv.json) | Copy of the [DTEK website](https://www.dtek-kem.com.ua/ua/shutdowns) schedule, updated every ~5 minutes |

- The schedule of a day comes from the source that updated it later (`updatedOn` of Yasno or `fact.update` of DTEK). The DTEK website usually publishes a new schedule 10-30 minutes earlier than Yasno.
- **Emergency shutdowns are only a flag.** During `EmergencyShutdowns` Yasno sends no schedule; the integration keeps the planned schedule of the day from DTEK or, without it, the last known one. The calendar shows an all-day «Emergency outage» event and the planned outages; the **Electricity** sensor shows `emergency`.
- If a source does not answer, the last received data is used. The last known schedule survives a Home Assistant restart.
- The attribute `schedule_sources` of the **Electricity** sensor shows the source of each day: `yasno`, `dtek` or `known`.

## Settings

- **Group** - your outage group, for example `43.1`. Find it at [Yasno](https://static.yasno.ua/kyiv/outages) or on the [DTEK website](https://www.dtek-kem.com.ua/ua/shutdowns).
- **Update interval** (options) - 1-30 minutes, 2-5 minutes is a good balance. Yasno serves the schedule through a CDN that caches it up to 5 minutes.

## Entities

Names of existing entities do not change: the device is «Київ ДТЕК &lt;group&gt;», for example `sensor.kiiv_dtek_43_1_electricity`.

- **Calendar** - planned outages and the all-day emergency flag.
- **Electricity** - `normal` / `planned_outage` / `emergency`.
- **Schedule updated on** - when the source of the schedule updated it (the latest of the sources).
- **Schedule data changed on** - when the planned outages of today and later really changed. Use it for notifications about a new schedule.
- Next outage / connectivity / reconnection, duration, countdowns, today's status.
- **Update schedule** button - requests the schedule right now.

Diagnostics of the entry (**Settings → Devices & services → Svitlo Kyiv → ⋮ → Download diagnostics**) contain the raw data of both sources and the source of each day.

## Installation

The quickest way to install this integration is via [HACS][hacs-url] by clicking the button below:

[![Add to HACS via My Home Assistant][hacs-install-image]][hasc-install-url]

If it doesn't work, adding this repository to HACS manually by adding this URL:

1. Visit **HACS** → **Integrations** → **...** (in the top right) → **Custom repositories**
2. Click **Add**
3. Paste `https://github.com/uhodav/ha-svitlo` into the **URL** field
4. Chose **Integration** as a **Category**
5. **Svitlo Kyiv** will appear in the list of available integrations. Install it normally.

## Upgrade from «Svitlo» (svitlo)

Version 0.6.0 renamed the integration from `svitlo` to `svitlo_kyiv`. The entity ids (and so history, automations and dashboards) can be kept:

1. Update the integration in HACS. Delete the folder `config/custom_components/svitlo` if it is still there (or disable the old «Svitlo» entry).
2. Restart Home Assistant. The old «Svitlo» entry shows an error - that is expected.
3. **Settings → Devices & services → Add integration → Svitlo Kyiv → Move the existing «Svitlo» entry**.
4. The settings and the entities move to «Svitlo Kyiv» with the same entity ids; the old entry is removed.

If the old integration still runs, the log says which entities could not be moved; remove it, restart Home Assistant, and the move finishes at the next start.

---

# 💡 Svitlo Kyiv (українською)

Інтеграція [Home Assistant][home-assistant] з графіками відключень електроенергії **Києва** (ДТЕК Київські електромережі): календар відключень, таймери, статуси.

> **Лише Київ.** Інші регіони та провайдер ДТЕК Київська область прибрано. Для інших регіонів використовуйте оригінальний проєкт https://github.com/ALERTua/ha-svitlo-yeah
>
> **Перейменовано:** домен інтеграції - `svitlo_kyiv` (було `svitlo`).

## Перехід зі «Svitlo» (svitlo)

1. Оновіть інтеграцію в HACS. Видаліть теку `config/custom_components/svitlo`, якщо вона лишилась (або вимкніть старий запис «Svitlo»).
2. Перезапустіть Home Assistant. Старий запис «Svitlo» показує помилку - так і має бути.
3. **Налаштування → Пристрої та служби → Додати інтеграцію → Svitlo Kyiv → Перенести наявний запис «Svitlo»**.
4. Налаштування та сутності переносяться в «Svitlo Kyiv» з тими самими ідентифікаторами (історія, автоматизації, панелі зберігаються); старий запис видаляється.

## Джерела даних

При кожному оновленні інтеграція опитує два джерела і для кожного дня бере найсвіжіший графік:

- [Yasno API](https://static.yasno.ua/kyiv/outages) - графік на сьогодні й завтра, ознака екстрених відключень;
- [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua/blob/main/data/kyiv.json) - копія графіка з [сайту ДТЕК](https://www.dtek-kem.com.ua/ua/shutdowns), оновлюється кожні ~5 хвилин. Сайт ДТЕК зазвичай публікує новий графік на 10-30 хвилин раніше за Yasno.

**Екстрені відключення - лише ознака.** Під час `EmergencyShutdowns` Yasno не надсилає графік; інтеграція зберігає плановий графік дня з ДТЕК або останній відомий. У календарі - подія «Екстрене відключення» на весь день і планові відключення; сенсор **Електрика** показує `emergency`. Якщо джерело не відповідає, використовуються останні отримані дані; останній графік зберігається і після перезапуску Home Assistant. Атрибут `schedule_sources` сенсора **Електрика** показує джерело кожного дня: `yasno`, `dtek` або `known`.

Налаштування: **група** (наприклад `43.1`) та **інтервал оновлення** в опціях (1-30 хвилин, оптимально 2-5). Назви наявних сутностей не змінюються. Сенсор **Графік змінено** - час, коли планові відключення сьогодні та далі справді змінились. Кнопка **Оновити графік** запитує графік одразу. Діагностика запису містить сирі дані обох джерел.

<!-- Badges -->

[gh-release-url]: https://github.com/uhodav/ha-svitlo/releases/latest
[gh-downloads-url]: https://github.com/uhodav/ha-svitlo/releases
[hacs-url]: https://github.com/hacs/integration
[hacs-image]: https://img.shields.io/badge/hacs-default-orange.svg?style=flat-square

<!-- References -->

[home-assistant]: https://www.home-assistant.io/
[hasc-install-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=uhodav&repository=ha-svitlo&category=integration
[hacs-install-image]: https://my.home-assistant.io/badges/hacs_repository.svg
[calendar-card]: https://www.home-assistant.io/dashboards/calendar/
