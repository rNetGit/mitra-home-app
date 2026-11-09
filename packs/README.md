# Pack data examples

Copy an example to `config/` (drop the `.example`) and edit it. Enable the pack in `config/family.json`
(`python onboard.py` step 7 does both).

- `festivals_indian_2026-27.example.json` -> `config/festivals.json` (pack `festivals`): list of {start, end, name}. Replace with your own culture's dates.

## Public holidays (`packs/holidays/`)

One JSON file per country (`us`, `uk`, `ca`, `in`): fixed days, nth weekday of a month, the last weekday before a
day, days from Easter, an optional `shift` in days, plus the weekend rule (`observed`: `us` or `uk`). `regions` adds
a state's, province's or nation's own days (`drop` removes national days it does not keep, as Scotland does). `python data/holidays.py [YEAR]` prints them.
A family copy in `config/holidays/<code>.json` wins and survives updates. Religious and cultural dates that move each
year come from the family's traditions (`data/traditions.py`), not from these files.

## Country profiles (`packs/country/`)

One JSON file per country: currency, units, address field labels, ID document types and renewal lead times, the tax
paper checklist (`tax.checklist`), the simplified home-office rule, which seasonal pack each climate maps to, and the
starter categorisation rules. `python data/country.py list` shows what is shipped (`us`, `uk`, `generic`). Countries
without a file use `generic.json` plus their currency and units. To adapt one for your family, copy a file to
`config/country/<code>.json` (same code as `country` in `config/family.json`) and edit it; your copy wins over the
shipped one and survives updates.
