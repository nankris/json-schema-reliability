# Codex's JSON schema flag made my extraction calls 4× pricier and no more reliable

*Draft. Tech in General experiment #030. Numbers are from 153 headless Codex calls on 2026-10-14/15. All $ figures are estimates at API list price.*

If you want structured data out of a model, the textbook advice is to use constrained decoding: hand the API a JSON Schema and the model literally can't produce anything that doesn't fit. Codex CLI exposes this as `codex exec --output-schema schema.json`. I wanted to know how much it actually helps over just asking for JSON.

## The setup

I took the intro sections of 50 Wikipedia articles: 10 each of people, cities, chemical elements, companies and historical events. I wrote one strict schema per domain, with required keys, nullable years, lists, a nested headquarters object, and fixed choices like "noble gas" or "treaty". Then I asked Codex (CLI 0.162.1, gpt-6.1-sol, ChatGPT Plus login) to extract each one three ways:

1. **Schema flag**: the schema in the prompt *and* `--output-schema`
2. **Plain, with schema**: the same prompt, no flag
3. **Plain, keys only**: "Reply in JSON with these keys: …", with no types and no allowed values

## What happened

| | Valid JSON | Matches schema | Est. cost per call |
|---|---|---|---|
| schema flag | 50/50 | 50/50 | 3.0¢ |
| plain, with schema | 50/50 | 50/50 | 0.8¢ |
| plain, keys only | 50/50 | 21/50 | 0.7¢ |

The grammar made no difference: with the schema in the prompt, plain JSON was perfect too. No code fences, no chatter, every enum right, every nested object shaped correctly.

Taking the schema *out* of the prompt was what hurt. The keys-only replies still parsed every time, but the model filled them its own way. Headquarters came back as "Espoo, Finland" instead of `{city, country}`, event kinds as "Volcanic eruption" instead of "disaster", populations as "more than 9.8 million". All sensible, and all wrong for the schema.

## The part I didn't expect: no cache hits

Every Codex call sends about 12K tokens of fixed instructions before your prompt. Normally that's cached, billed at $0.10 per million instead of $2. On the plain calls it was cached 100 times out of 100. With `--output-schema` it was cached **2 times out of 53**. I re-ran the same schema prompt three times back to back to make sure, and got zero cached tokens all three times.

So the flag made each call about four times more expensive at list price, with nothing to show for it on this data. I can't tell from the outside whether Codex or the API is responsible, but it's very consistent.

## One more thing to watch

On Vienna, the text says the population is "just over two million". The plain prompt returned `null` for population. The schema-forced run returned `2000000`. Forcing a type can push the model to commit to a number it wasn't given. It happened once here, but that's the risk.

## The takeaway

For small extraction jobs in Codex: **put the schema in the prompt, skip `--output-schema`**. You get the same reliability and keep the cache. Reach for the flag when a parse failure would be expensive or the schema is too big to trust the model with, and check your cached-token counts when you do.

*Caveats: one model and build, one call per prompt, clean Wikipedia text. 50 prompts can't detect failure rates below a couple of percent. Full tables, schemas, prompts and raw logs are in the repo README.*
