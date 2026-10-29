# Nominal SQL library

Version 1 · PostgreSQL 18 · English/USA (`en_US`) and German/Germany (`de_DE`).

[TOC]

## Quick start

All generation routines are **stored procedures**, created with `create procedure`, and invoked with `call`. Python performs no name, address, coordinate, physical-attribute, phone, or email generation. It binds request parameters, reads the returned JSON, and renders Jinja templates. JavaScript handles interaction and projects existing coordinates onto the globe.

```sql
-- OUT arguments are supplied as null in a top-level CALL.
call nominal.batch('en_US', '42', 0, 10, null);
call nominal.batch('de_DE', '42', 0, 10, null);
-- The next ten contacts, with the same locale and seed:
call nominal.batch('de_DE', '42', 1, 10, null);
```

Each call returns one row, with an output column named `result`. It contains metadata and a `contacts` array. Request batch 0 again to reproduce those contacts exactly. In PL/pgSQL, pass a local variable to receive an OUT parameter instead of `null`.

```sql
do $$
declare result jsonb;
begin
  call nominal.batch('en_US','my demonstration',0,10,result);
  raise notice '%', result->'contacts'->0;
end $$;
```

## Common argument contract

| Argument | SQL type | Meaning |
|---|---|---|
| `p_locale` | `text` | Exact locale identifier: `en_US` or `de_DE` in v1. Included in every random stream. |
| `p_seed` | `text` | Case-sensitive UTF-8 string, 0–64 characters. `42`, `042`, and `forty-two` are different seeds. Empty string is valid. |
| `p_position` | `bigint` | Absolute, zero-based contact position. Normally nonnegative. |
| `p_stream` | `text` | Stable namespace for one draw, such as `name/first` or `geo/z`. Different streams avoid coupling fields. |
| `p_dictionary` | `jsonb` | Locale's frozen `nominal.assets.dictionary` snapshot. |
| `p_model` | `jsonb` | Locale's frozen `nominal.assets.model` Markov transitions. |

`batch` is the validated public entry point. Other generation procedures are building blocks; callers must supply a matching, nonempty dictionary/model and valid arguments. They are not separate public HTTP endpoints. The benchmark and dictionary rebuild procedures are restricted to the administrative database role.

## Batch

```sql
call nominal.batch(
  p_locale text, p_seed text, p_batch bigint, p_size integer,
  out result jsonb
);
```

- `p_batch`: zero-based index, 0–100,000,000.
- `p_size`: 1–100 in SQL; the web app offers 10, 25, or 50.
- Absolute position = `p_batch * p_size + index_within_batch` (index starts at 0).
- `result`: `{version, locale, seed, batch, size, start, contacts}`. Each contact includes `position`, `locale`, `name`, `address`, `coordinates`, `physical`, `phone`, and `email`.
- Unsupported locale, null arguments, excessive seed length, and invalid sizes/indexes raise exceptions.
- Loads the locale assets once per batch, then calls `contact` for each position. Does not store generated contacts or modify database state.

**Position stability:** changing the batch size changes page boundaries, not people. Position 25 is batch 2/index 5 at size 10, or batch 1/index 0 at size 25. Both produce the same contact. HTML displays positions and batch numbers starting at 1; SQL and API use zero-based values. The HTTP API adds `elapsed_ms`, which is live round-trip timing and is intentionally not deterministic. Contact values are deterministic.

## Randomness primitives

### Uniform

```sql
call nominal.uniform('en_US','42',0,'example',null);
-- Signature: (p_locale text, p_seed text, p_position bigint,
--             p_stream text, out value double precision)
```

Encode `[locale, seed, position, stream]` as a PostgreSQL JSONB array. Hash its textual representation using built-in MD5. Take the first 13 hexadecimal digits (52 bits), convert to integer `h`, then return `(h + 0.5) / 2^52`. Values lie strictly in **(0, 1)**, so logarithms and inverse transforms avoid endpoints. JSON encoding prevents concatenation collisions, including seeds with separators or quotes.

This is deterministic **pseudorandomness**, suitable for synthetic data. MD5 is not used for passwords, security tokens, cryptographic randomness, or proving statistical independence. No global RNG state, `random()`, or `setseed()` is involved. Reproducibility is promised for this frozen library version and its data snapshots, not arbitrary future algorithm/dictionary changes.

### Integer

```sql
call nominal.integer('en_US','42',0,'example',10,20,null);
-- (p_locale text, p_seed text, p_position bigint, p_stream text,
--  p_min integer, p_max integer, out value integer)
```

Returns an integer in the inclusive range `[p_min, p_max]` using `min + floor(u * (max-min+1))`. Rejects reversed bounds. Finite 52-bit resolution introduces negligible discretization bias when the interval does not divide `2^52`; this is not a cryptographic sampler.

### Normal

```sql
call nominal.normal('en_US','42',0,'height',172,9,null);
-- (p_locale text, p_seed text, p_position bigint, p_stream text,
--  p_mean double precision, p_sd double precision,
--  out value double precision)
```

Box–Muller: `mean + sd * sqrt(-2 * ln(u)) * cos(2 * pi() * v)`. The two uniforms use distinct stream suffixes `/u` and `/v`. Returns an unbounded normal variate; negative standard deviation is rejected, zero is allowed.

### Choose

```sql
do $$
declare d jsonb; item text;
begin
  select dictionary into d from nominal.assets where locale='de_DE';
  call nominal.choose(d,'de_DE','42',0,'last','example/surname',item);
  raise notice '%',item;
end $$;
-- (p_dictionary jsonb, p_locale text, p_seed text,
--  p_position bigint, p_category text, p_stream text, out value text)
```

Uniformly selects an item from a named dictionary array using its zero-based index. Categories: `male`, `female`, `last`, `corpus`, `suffix`, and `eyes`. Missing or empty categories raise an exception. Names are uniformly selected from static lists; they do not reproduce population name frequencies.

## Contact construction

The following procedures share dictionary/model and locale/seed/position inputs. They are independently callable using a `do` block as shown below.

### Full name

```sql
-- (p_dictionary jsonb, p_locale text, p_seed text,
--  p_position bigint, out value jsonb)
call nominal.full_name(d,'en_US','42',0,n);
```

Selects a first-name category, first name, surname, and optional second given name. Eight equiprobable format branches include plain names, full middle names, a middle initial, `Dr.`, locale-sensitive `Mr./Ms.` or `Herr/Frau`, and US `Jr.`. Some branches intentionally result in plain names. Output: `{first, last, full}`. Category selection is a formatting choice, not a claim about gender identity.

### Word

```sql
-- (p_dictionary jsonb, p_model jsonb, p_locale text,
--  p_seed text, p_position bigint, out value text)
call nominal.word(d,m,'de_DE','42',0,w);
```

An **order-2 character Markov chain**, trained in PostgreSQL from locale-specific street-word corpora. Start with `^^`; the last two characters determine a weighted distribution of the next character. `$` ends a word. Every step gets its own counter stream. Up to 18 steps and four attempts; accept lengths 4–14, otherwise pick a corpus word as a deterministic fallback. Title-case the output. German characters remain intact.

The result resembles the locale's spelling but is invented, and can occasionally be an odd or existing word. This is statistical word construction, not a language model and not a guarantee of grammatical text. The UI does not claim postal deliverability.

### Address

```sql
-- (p_dictionary jsonb, p_model jsonb, p_locale text,
--  p_seed text, p_position bigint, out value jsonb)
call nominal.address(d,m,'de_DE','42',0,a);
```

Chooses a real city/region anchor, a five-digit postal code within its illustrative range, a Markov street root, locale street suffix, and house number. US format: `7758 Fiew Way, Austin, TX 78705`; German format: `Rosenweg 42, 10115 Berlin`. Variations include US apartments/suites and German apartment/house-letter forms. US house numbers range 1–9999, German 1–250. Output includes formatted and structured address components plus internal telephone routing fields. `contact` removes those internal fields.

Postal codes and street names are synthetic. A range is not an authoritative list of assigned postal codes. Country-city spelling and formatting are locale-aware; generated addresses must not be used for delivery.

### Coordinates

```sql
call nominal.coordinates('en_US','42',0,null);
-- (p_locale text, p_seed text, p_position bigint, out value jsonb)
```

Draw independent `u,v` uniformly in (0,1). Set `z=2u-1`, `latitude=degrees(asin(z))`, and `longitude=360v-180`. On a sphere, surface area is proportional to `d(longitude) * d(sin(latitude))`, so these samples are **uniform by area**. Uniform latitude would incorrectly concentrate points at the poles.

Output: `{latitude, longitude}` in degrees. Coordinates are **global and independent of the postal address**. Restricting coordinates to the country would violate the whole-sphere requirement. The globe displays a sample; equal-area statistical tests use many draws, not a ten-point picture.

### Physical

```sql
-- (p_dictionary jsonb, p_locale text, p_seed text,
--  p_position bigint, out value jsonb)
call nominal.physical(d,'en_US','42',0,p);
```

Height: Normal(172 cm, 9 cm); weight: Normal(75 kg, 12 kg). Rejection sampling enforces height 110–230 and weight 35–180, making these **truncated normals**, rounded to one decimal. The lower weight boundary changes the mean slightly. At most 100 attempts per attribute; exhaustion is effectively negligible at these bounds. Eye color is a uniform discrete choice of five localized labels. Height and weight are independent illustrative distributions, not a demographic or medical model.

### Phone

```sql
-- (p_address jsonb, p_locale text, p_seed text,
--  p_position bigint, out value text)
call nominal.phone(a,'en_US','42',0,phone_number);
```

Uses the selected address anchor's area code and an official fictional number block. US: NANPA `555-0100` through `555-0199`, with national, international, and dotted formats. Germany: Bundesnetzagentur drama ranges for Berlin (`030 23125xxx`), Frankfurt (`069 90009xxx`), Hamburg (`040 66969xxx`), Köln (`0221 4710xxx`), München (`089 99998xxx`), each with 000–999 endings. Formats vary between national slash, parenthesized area code, and `+49` international form.

Numbers can repeat. Never assume phone uniqueness or use these numbers for verification calls.

### Email

```sql
-- (p_name jsonb, p_locale text, p_seed text,
--  p_position bigint, out value text)
call nominal.email(n,'de_DE','42',0,email_address);
```

Lowercase first/surname, transliterate German umlauts and ß, strip remaining non-ASCII punctuation, and append an eight-hex-digit locale/seed namespace plus the absolute position. Uses reserved `example.com`. Local part is capped to fit RFC limits for the supported position range. Emails are unique **within one locale/seed**, due to position. The finite hash prefix means global uniqueness across every seed is not guaranteed. These are test addresses, not inboxes.

### Contact

```sql
do $$
declare d jsonb; m jsonb; c jsonb;
begin
  select dictionary,model into d,m from nominal.assets where locale='de_DE';
  call nominal.contact(d,m,'de_DE','42',123,c);
  raise notice '%',c;
end $$;
-- (p_dictionary jsonb, p_model jsonb, p_locale text,
--  p_seed text, p_position bigint, out value jsonb)
```

Composes `full_name`, `address`, `coordinates`, `physical`, `phone`, and `email`. Returns the complete contact JSON. All formatting happens in SQL, including spaces, localized suffixes, titles, case conversion, numeric rounding, and email transliteration.

## Dictionary architecture & extension

| Table | Purpose |
|---|---|
| `nominal.locales` | One row per locale; identifier, label, country. |
| `nominal.names` | Locale, kind, ordinal, value. Given names and surnames in one extensible table. |
| `nominal.terms` | Locale, kind, ordinal, value. Corpus words, street suffixes, discrete values. |
| `nominal.cities` | Locale, ordinal, city/region, postal range, fictional telephone routing. |
| `nominal.markov_transitions` | Trained bigram context, next character, frequency, cumulative/total weights. |
| `nominal.assets` | Frozen, ordered JSON snapshots for efficient repeated generation. |

The initial dataset contains **4,109 distinct-per-category name entries**. US: 322 male given names, 381 female given names, 1,000 surnames; Germany: 999 male given names, 1,003 female given names, 404 surnames. Exact counts can be inspected with the query below. Street vocabulary contains 449 total entries across corpus, suffix, and eye-color categories. US city anchors: 15; German anchors: five metropolitan areas with fictional telephone blocks.

```sql
select locale,kind,count(*) from nominal.names group by locale,kind order by locale,kind;
```

Hundreds of thousands of first/surname combinations, middle-name formats, Markov street roots, house and postal numbers, phone variations, physical attributes, coordinates, and position-specific emails support batches well beyond a million distinct contacts. Names and phone numbers may repeat, just as in real contact data; this is not a guarantee of a million unique full names. There is no pre-generated million-person file and no growing contact table.

Names are static constants extracted from the MIT-licensed Faker 40.44.0 dictionaries. **Faker is a development-only extraction dependency**, not a runtime generator. Its license is included in `data/LICENSE-Faker.txt`. Corpora and city anchors are curated project data. CSV files contain input dictionaries, not generated user records.

### Rebuild locale

```sql
call nominal.rebuild_locale('de_DE');
-- (p_locale text), no OUT parameter; ADMIN ONLY
```

Builds order-2 transition counts from lowercase corpus words with start/end sentinels, computes weighted cumulative distributions, and snapshots dictionary arrays in ordinal order. Existing snapshot is replaced. Run once at initialization or during an intentional versioned dictionary update. **Changing dictionaries or algorithms can change deterministic output.** Preserve the v1 CSV files and procedures to reproduce v1; release future changes under a new library version/schema.

To add a locale: insert one metadata row and matching names/terms/cities, extend locale-specific name/address/phone formatting where needed, rebuild its assets, and expose it in the app's locale allowlist. A new country needs formatting rules; inserting names alone does not magically implement its postal/phone conventions. Shared lookup tables stay shared.

## Benchmark

```sql
call nominal.benchmark('en_US','benchmark-v1-1',100000,null);
-- (p_locale text, p_seed text, p_count integer, out result jsonb)
```

Admin-only; count 1–1,000,000. Loads one locale snapshot and constructs **every field** for each of `count` contacts. Serializes each JSON contact and folds it into a running MD5 checksum so no work is skipped. Measures SQL wall time with `clock_timestamp()`. Output: `locale`, `count`, `seconds`, `users_per_second`, `checksum`, PostgreSQL `server` version, and `finished_at`. It does not return or retain all generated contacts, so memory stays bounded.

The published test runs three trials of 100,000 contacts per locale, after a small warm-up, sequentially on the shared VPS. This measures 600,000 contacts in total. It excludes network/HTML from SQL throughput and separately records client round-trip time. Aggregate rate = total contacts / total SQL seconds. [Measured results](/benchmark) · [Raw JSON](/api/benchmark).

## Deployment, permissions & HTTP

The database is isolated in its own PostgreSQL container. The Python app has SELECT and generation CALL access; it cannot rebuild snapshots, benchmark, create tables, or write lookup data. Its default transactions are read-only with an eight-second statement timeout. HTTP requests accept bounded batch sizes and use Psycopg bound arguments, never SQL string interpolation. The admin password and app password are separate, stored only in a mode-600 deployment `.env`, excluded from source control. Database port is bound to loopback only.

```python
cursor = await connection.execute(
    "call nominal.batch(%s,%s,%s,%s,null)",
    (locale, seed, page, size),
)
result = (await cursor.fetchone())[0]
```

`GET /api/contacts?locale=en_US&seed=42&page=0&size=10` returns procedure JSON plus measured `elapsed_ms`. `/download` exports the **same batch**, not a separately randomized dataset. `/api/docs` documents endpoints. Exports contain fictional names and reserved contact channels; do not use them as real personal records.

## References

- [PostgreSQL CREATE PROCEDURE](https://www.postgresql.org/docs/18/sql-createprocedure.html) and [CALL / OUT parameters](https://www.postgresql.org/docs/18/sql-call.html).
- [Uniform sphere point picking and area element](https://mathworld.wolfram.com/SpherePointPicking.html).
- [NANPA fictional 555 telephone numbers](https://www.nanpa.com/numbering/555-line-numbers).
- [Bundesnetzagentur fictional drama telephone numbers](https://www.bundesnetzagentur.de/DE/Fachthemen/Telekommunikation/Nummerierung/DramaNumbers/artikel.html).
- [IANA reserved example domains](https://www.iana.org/help/example-domains).
- [Faker static dictionaries and MIT license](https://github.com/joke2k/faker).
