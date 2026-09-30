# Custom JSON expressions

The DSL is a deterministic subset with MailWebhook extensions. Do not assume
features from other expression or template languages. Read
[custom-json-pipeline.md](custom-json-pipeline.md) for the root values and mapper
boundary; read [extraction-helpers.md](extraction-helpers.md) for the seven helper
contracts.

## Templates and expression detection

Scalars remain literals. Arrays recursively evaluate their elements. Plain
objects recursively evaluate their values. A single-key object whose key is a
supported operator evaluates as that operator instead. Objects with exactly
`vars` and `output` are scoped blocks, described below.

A single unknown dotted key, including an unsupported `string.*`, `regex.*`, or
`call.*` name, is an operator error. An unrecognized undotted key generally stays
a literal object key; for example, `length` does not calculate an array length.
Multiple-key objects remain templates even if a key is an operator name. To
emit a literal operator-shaped object without evaluation, store it under static
`meta` and return it through `var`.

There is no interpolation inside ordinary strings and no evaluation of strings
as code. Return values of `var` and helper calls are data, not recursively
reinterpreted expression templates.

## Lookup and scope

`{"var":"message.from[0].email"}` reads a path. Its argument must be a string;
the JsonLogic array form for a fallback value is unsupported. Use `if` or `or`
explicitly, observing their truthiness behavior.

- Dots traverse identifier-like object keys; numeric nonnegative `[index]`
  accesses arrays. Missing values, invalid paths, and out-of-range indexes return
  `null`.
- Quoted bracket keys, negative indexes, wildcards, and dynamic path expressions
  are unsupported. Keys containing hyphens or literal dots cannot be addressed
  through this path syntax. For example, `message.headers.x-priority` cannot read
  that header; routing header matchers use a separate contract.
- An empty path returns the entire evaluation root. It is not shorthand for an
  iterator's current element. Use the iterator alias instead.
- The nearest lexical binding wins for a path's head. If that binding exists but
  a nested property is missing, the result is `null`; it does not fall back to an
  outer value with the same head.
- Array helpers expose `item` or their chosen `as` alias; reducers expose
  `current` and `accumulator`. Nested helpers retain outer aliases unless an inner
  helper shadows them.
- Locals from scoped blocks are addressed as `vars.<name>`. The closest local
  variable wins, then outer scoped variables, then top-level variables. Root
  `message`, `ctx`, and `meta` remain available.

## Core operators

The table's arguments sit under a single operator key. Each `a`, `b`, `value`,
or similar value may itself be an expression unless stated otherwise.

| Operator | Argument shape | Behavior |
| --- | --- | --- |
| `var` | String path | Lookup described above. |
| `if` | `[condition, then, else]` | Evaluates only the selected branch. `else` is optional and defaults to `null`. This is one condition, not chained condition/value pairs; later array entries are ignored. |
| `and` | `[a, b, ...]` | Short-circuits at the first falsey result, otherwise returns the last result. Empty input returns `null`. |
| `or` | `[a, b, ...]` | Short-circuits at the first truthy result, otherwise returns the last result. Empty input returns `null`. |
| `!` | One expression directly | Boolean negation. Do not wrap the operand in a one-element array: the array itself would be tested. |
| `==`, `===` | Exactly `[a, b]` | Equal; both spellings use the same equality semantics. |
| `!=`, `!==` | Exactly `[a, b]` | Not equal; both spellings use the same semantics. |
| `>`, `>=`, `<`, `<=` | Exactly `[a, b]` | Ordered comparison; incompatible operands return `null`. Strings compare lexically. |
| `in` | Exactly `[needle, haystack]` | Substring membership for strings, element membership for arrays, key membership for objects. Unsupported membership returns `null`. |
| `cat` | `[a, b, ...]` | Concatenates string representations; `null` becomes `""`. Non-array argument returns `""`. |
| `substr` | `[value, start, length]` or `{value, start, end}` | Coerces non-null value to string. `start` defaults to zero in object form. Optional `length`, or object-form `end`, is a **length**, not an absolute end index. Omission takes the remaining string. |
| `merge` | `[object, object, ...]` | Shallow merge, later keys win; non-object items are ignored. Non-array argument returns `{}`. |

Truthiness follows the runtime: `null`, `false`, zero, empty string, empty array,
and empty object are falsey. Nonempty strings including `"false"` and `"0"` are
truthy. Equality does not coerce a numeric string into a number, but booleans and
numbers compare as equal when their values correspond: `true` equals `1` even with
`===`. Arrays and objects compare by their contents. `or` is a truthy fallback,
not a null-only coalescing operator; preserve meaningful zero/false values with
an explicit equality-to-null condition.

Negative string indexes follow string slicing semantics. `substr`'s third list
argument and object `end` both slice from `start` to `start + length`.

## String operators

| Operator | Argument shape | Behavior/defaults |
| --- | --- | --- |
| `string.lower` | One expression directly | Lowercase string representation; `null` stays `null`. |
| `string.upper` | One expression directly | Uppercase string representation; `null` stays `null`. |
| `string.trim` | One expression directly | Trim leading/trailing whitespace from the string representation; `null` stays `null`. |
| `string.slice` | `{value, start, end}` | String slice; `start` defaults to `0`; omitted or literal-null `end` takes the rest. Here `end` is an absolute exclusive index. |
| `string.split` | `{value, sep}` | Exact separator split, preserving empty parts. Missing/null value or separator returns `null`; empty separator returns `null`. |
| `string.join` | `{items, sep}` | `items` must evaluate to an array; otherwise `null`. Separator defaults to `""` and falsey separators become `""`; null items become empty strings, other items are stringified. |
| `string.replace` | `{value, find, with, count}` | Literal substring replacement. `value`, `find`, `with` must be non-null. Omitted/null, negative, or **zero** count replaces all occurrences; positive count bounds replacements. |

Object-form properties above can be expressions. Invalid numeric conversions
or other ordinary operator errors return `null`. Stringification is not a JSON
serializer; avoid using it to encode nested objects or arrays.

## Regex operators

| Operator | Argument shape | Result |
| --- | --- | --- |
| `regex.match` | `{value, pattern}` | Boolean search anywhere in the string, not an implicit full match. |
| `regex.replace` | `{value, pattern, with}` | Replaces all regex matches. |

Arguments are evaluated and non-null values coerced to strings. Use regex
anchors for full-value matching and inline flags such as `(?i)` for
case-insensitivity. JSON must escape backslashes. Replacement capture references
use `"\\1"` or `"\\g<name>"`; `$1` is literal text. There is no separate flags or
replacement-count argument and no operator that returns match groups as an
array. Invalid patterns or replacements return `null`; a detected timeout stops
the mapper with an error. Risky-pattern linting selects guarded execution; it
does not make a valid pattern an unsupported capability.

## Array operators

| Operator | Object argument | Compact array argument | Result for empty input |
| --- | --- | --- | --- |
| `map` | `{over, as, do}` | `[array, expression]` | `[]` |
| `filter` | `{over, as, where}` | `[array, predicate]` | `[]` |
| `find` | `{over, as, where}` | `[array, predicate]` | `null` |
| `reduce` | `{over, do, start}` | `[array, expression, initial]` | `start`/`initial`, or `null` if absent |
| `some` | `{over, as, where}` | `[array, predicate]` | `false` |
| `all` | `{over, as, where}` | `[array, predicate]` | `true` |
| `none` | `{over, as, where}` | `[array, predicate]` | `true` |

`over` is evaluated once and must yield an array; other types return `null`.
`map` evaluates `do` for each item. `filter` retains the original items whose
predicate is truthy. `find` returns the first matching original item.
`some`/`all`/`none` return booleans and short-circuit. Reducers evaluate `start`
once, then evaluate `do` in sequence with `current` and `accumulator`; there is no
`as` option for `reduce`.

For other helpers, `as` is a literal identifier, defaults to `item`, and matches
`^[A-Za-z_][A-Za-z0-9_]*$`. Reserved aliases `message`, `ctx`, `meta`, `vars`,
`current`, and `accumulator` are rejected. Compact array form uses `item`; it has
no custom-alias slot. No iterator index binding is provided.

For example, this expression produces attachment names without mutating the
message or its attachments:

```json
{
  "map": {
    "over": {"var": "message.attachments"},
    "as": "file",
    "do": {"var": "file.filename"}
  }
}
```

## Scoped blocks

An object with exactly `vars` and `output` creates a local block. Its variable
array must be present, even if empty; each entry needs a valid unique `name` and
an `expr`. Variables are evaluated in order. The result is the evaluated block
output, without the local declarations. Local variables do not escape the block.
An extra object key disables block recognition and makes the object a template.

The block can appear in an output value or an operator payload, including inside
an array helper's `do`. For example:

```json
{
  "vars": [
    {
      "name": "clean_subject",
      "expr": {"string.trim": {"var": "message.subject"}}
    }
  ],
  "output": {"or": [{"var": "vars.clean_subject"}, "No subject"]}
}
```

Top-level `vars[].expr` cannot directly be a block due to its expression schema;
see [custom-json-pipeline.md](custom-json-pipeline.md). Within a block, `expr` can
be a template as well as an operator. If an inner variable shadows an outer name,
its initializer can still read the outer value before the new local binding is
assigned; later references see the local value.

To emit a literal two-property object named `vars` and `output`, merge the
properties from separate objects: `{"merge":[{"vars":[]},{"output":"stored"}]}`.
This escape works because `merge` returns data instead of evaluating its result
again.

## Helper calls

Generic form is `{"call":{"fn":"extract.urls","args":{...}}}`.
`fn` must be a literal supported helper name; `args` is an optional object.
Prefixed form is `{"call.extract.urls":{...}}`; use `{}` when no arguments are
needed. Arguments are evaluated as templates, so individual arguments can use
`var`, operators, and scoped blocks. Both forms invoke the same helper contract.

The complete helper inventory is `transform.html_to_text`, `extract.urls`,
`extract.bullet_list`, `extract.reply_segments`, `extract.key_value_pairs`,
`extract.tables`, and `extract.dom`. Every name has a `call.<name>` form in addition
to generic `call`. Unsupported names are rejected. Read
[extraction-helpers.md](extraction-helpers.md) before choosing modes, defaults, or
result paths; passing `text` alone does not necessarily select text mode.

## Limits and absent operations

One mapper evaluation shares a 10,000-node budget across top-level variables,
output, and loop iterations; maximum evaluator depth is 50. A repeated expression
consumes budget repeatedly. Depth, node, timeout, helper configuration, and other
explicit transform errors stop the mapper. Most ordinary type/arity/operator
exceptions yield `null` instead. No DSL `try`/`catch` is provided.

Regex calls use a 50 ms timeout parameter; risky patterns are sent through the
guarded execution path. Other regex calls run directly with slow-call monitoring,
so do not treat 50 ms as a universal hard wall-clock deadline. Regular helper
calls enforce a roughly 200 ms elapsed-time budget; reply segmentation uses its
dedicated runtime limits. These are execution guardrails, not route JSON options.

The inventories above are exhaustive. In particular, there are no arithmetic,
numeric parsing, length/count, sorting, date formatting, object-key iteration,
dynamic property access, generic null-coalescing, arbitrary function, network,
or mutation operators. An extractor's returned count or normalized key is data
from that helper, not an additional DSL operator.
