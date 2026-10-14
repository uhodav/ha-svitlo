# Changelog

## 0.7.1

- The state of the calendar (`on`, current event) is the group schedule again; outages of the house are only in the event list. Automations that treat a running calendar event as a planned outage are not confused by an emergency of the house.
- Outages of the house in the event list have the address in `description` (planned group outages have `Definite`, the emergency flag `Emergency`): filter planned outages by `description == 'Definite'`.

## 0.7.0

Outage of your house from the DTEK website (optional).

- Address step in the setup and in the options: paste the `ajax` request of the address form of the DTEK website (Copy as cURL), then select the house of the street.
- The address request is not behind the captcha of the website; it only needs the CSRF pair of the website (cookie `_csrf-dtek-kem` and header `X-CSRF-Token`), taken from the pasted request.
- New sensors: **House electricity** (`normal` / `emergency` / `planned` / `stabilization` / `other`, with the reason of DTEK, start and estimated restoration in the attributes), **House outage start**, **House estimated restoration**.
- The calendar shows the emergency and planned works of the house with their exact time.
- When the website stops accepting the CSRF pair, Home Assistant asks for a new request (re-authentication); the group schedule keeps working.
- Options are a menu now: settings, address of the house, stop tracking the house.
- The CSRF pair is removed from the diagnostics.

## 0.6.0

Svitlo Kyiv: Kyiv only, second schedule source.

- The integration is renamed to `svitlo_kyiv` («Svitlo Kyiv»); the setup moves an existing `svitlo` entry with the same entity ids.
- Kyiv only: other regions and the DTEK Kyiv Oblast provider are removed; the setup asks only for the group.
- Second source: copy of the DTEK website schedule (Baskerville42/outage-data-ua); the latest schedule of each day wins.
- Emergency shutdowns are only a flag: the planned schedule of the day stays (DTEK copy or the last known one, kept across restarts).
- The last schedule is kept on request errors.
- **Update schedule** button attached to the device; minimal update interval 1 minute.
- **Schedule data changed on** sensor, diagnostics, `schedule_sources` attribute.

## 0.5.3

Svitlo: fork of [ALERTua/ha-svitlo-yeah](https://github.com/ALERTua/ha-svitlo-yeah).

- **Update schedule** button (`force_update_schedule`).
- **Last schedule request** sensor.
