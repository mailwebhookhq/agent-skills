# Validate the authored artifact

Validate only the requested artifact and its surrounding contract. Syntax checks
alone do not establish valid matching, runtime success, or delivery compatibility.

## Checks for every configuration

- Parse as strict JSON: no comments, trailing commas, duplicate keys, or nonfinite
  numbers. Preserve required strings, numbers, booleans, arrays, and objects.
- Check all keys and names against the relevant reference, including nested
  rules, variable names, helper arguments, and step order. Do not count silently
  ignored keys as supported capabilities.
- Validate each `map.custom_json` step's `args` against the included
  [mapper configuration schema](schemas/custom-json-mapper.schema.json) with a
  Draft 2020-12 validator when available. Follow the
  [mapper validation boundaries](custom-json-pipeline.md#output-and-validation-boundaries)
  as well; schema acceptance does not establish successful execution. Other
  configuration blocks still require their respective contract checks.
- Distinguish missing, null, empty string, empty array, false, and zero when they
  affect matching or output. Decide whether the target expects omitted keys,
  nulls, defaults, or a failure; the mapper does not infer that choice.
- Validate rule behavior separately from the pipeline. Preprocessing cannot
  change whether the original email matched the rule.
- For full routes, check endpoint ID shape and requested enablement. Local
  validation cannot prove endpoint ownership, signing-key availability, account
  limits, or successful delivery.

## When execution testing is available

Use an already available, compatible preview or test facility. This skill does
not assume private libraries, a local development environment, or an additional
validation API. Check the available facility's documented behavior and side
effects; a send-test action can deliver a real webhook and bypass rule matching.

| Layer | What to check |
| --- | --- |
| Route create/update | Correct API envelope and types; only the intended fields change. |
| Rule | Evaluate representative routing metadata, including nested conditions and missing values. Request acceptance alone does not fully validate nested rules. |
| Pipeline | Supported step names and arguments, correct order, and exactly one final mapper. Compilation alone can accept a mapper-less pipeline. |
| Execution | Actual extraction, expression behavior, execution-time argument checks, and output schema. |
| Delivered JSON | Required fields/types, timestamp representation, and the expected body shape. |

Use fixed identifiers and timestamps where the test facility supports them.
Compare emitted values and types with explicit expectations; inspect null/default
results from expression errors. Verify required capabilities against the target
deployment when its supported feature set is uncertain. When execution testing
is unavailable, perform contract review and clearly label the artifact as not
execution-tested.

## Representative cases

Select cases relevant to the requested configuration; these also serve as skill
evaluation prompts when its references change.

| Request or scenario | Required behavior |
| --- | --- |
| Match invoice **or** receipt from a vendor, excluding one sender | One `subject_contains` list uses OR; separate populated fields use AND; the exclusion works on an otherwise matching message. |
| Match both subject terms | Use separate child conditions under `all`; a message with only one term does not match. |
| Exclude messages with MIME-typed attachments | Negate `attachments_mime: ["*/*"]`; an attachment whose type matches that glob fails. Missing or malformed content types can evade it, so this is not a guaranteed attachment-count check. Do not invent `has_attachments`. |
| Rename fields and map the changed message | Only supported preprocessing targets are used; the mapper sees changes. Rule matching remains based on the original metadata. |
| Remove large image attachments | MIME and size are AND within one step; attachment size equal to the threshold is retained. |
| Produce subject/sender and optional extracted order ID | Expected strings appear, absent sender/body/ID have the chosen fallback, and the final body is an object. |
| Repeated key/value labels or table headers | First-value and all-values paths are intentionally different; table lookup uses returned normalized/disambiguated keys. |
| Nested iterators with local variables | Aliases refer to their intended item; `vars.*` sees the nearest binding and still permits outer fallback. |
| DOM records from a known template | Required selector engine/projection are supplied; field selectors stay within each container; missing fields and truncation are handled. |
| Emit a literal object whose keys collide with DSL syntax | Use the documented construction/escape behavior; it must not accidentally become an operator or a scoped block. |
| Fix malformed or unsupported configuration | Identify the exact unsupported key/operator/shape; never silently introduce a new feature or broaden a rule. |
| Update only a rule on an existing route | Supply only the changed API property; preserve destination and pipeline. |

Include at least a matching and a nonmatching email for rules; absent/empty input
and duplicate/repeated structures for extraction; and a target-type check for
each computed output. Regex cases should cover both match and no-match without
depending on engine failure as control flow.
