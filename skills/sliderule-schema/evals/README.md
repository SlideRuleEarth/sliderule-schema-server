# Evaluations

Data-driven evaluations for the `sliderule-schema` skill, following the
schema described in Anthropic's [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

Each `*.json` file is a single eval with four fields:

- `skills` — which skills are loaded for the run
- `query` — the user prompt in natural language
- `files` — files the agent starts with in context (empty for this skill;
  all state lives behind HTTPS)
- `expected_behavior` — a list of behaviors a correct answer must exhibit

Anthropic's docs are explicit that **there is no built-in runner** — see
the "Evaluation Structure" section of the best-practices page:

> There is not currently a built-in way to run these evaluations. Users
> can create their own evaluation system.

So these files are author-facing rubrics, not a CI test suite. To grade:

1. Start a Claude session with `skills` loaded and only those.
2. Paste `query` as the first user message.
3. Observe tool calls + final response.
4. Check every `expected_behavior` entry against what Claude did.
5. Optionally re-run the same query **without** the skill loaded and compare
   — per the doc, the with/without delta is the real measure of skill value.

## Test with weaker models

The best-practices doc recommends testing with Haiku in particular — it's
the most likely to skip SKILL.md guidance and answer from training data.
A skill that works on Haiku usually works everywhere.

## The evals

| File | Catches |
| ---- | ------- |
| [01-param-lookup-inheritance.json](01-param-lookup-inheritance.json) | Misrouting `cnf` to `core.json` on the inheritance assumption |
| [02-output-column-condition.json](02-output-column-condition.json) | Missing the `condition: "stages.phoreal"` gate when explaining missing columns |
| [03-cross-skill-boundary.json](03-cross-skill-boundary.json) | Answering narrative/how-to questions with schema data instead of redirecting to `sliderule-docsearch` |
| [04-resolution-param.json](04-resolution-param.json) | Fabricating a non-existent `resolution` param, or conflating `res` (posting) with `len` (extent length) |
| [05-field-selector-lookup.json](05-field-selector-lookup.json) | Skipping the two-hop `fields_url` → `selectors[].url` walk and hallucinating field names |
| [06-required-pairings.json](06-required-pairings.json) | Treating `atl08_class`'s `required_pairings` (cnf=0, srt=0) as optional suggestions instead of hard requirements |
