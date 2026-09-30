# Routing rule contract

`rule` is a JSON object. Author only the keys below, with arrays of strings,
string-valued header objects, and recursively well-formed child rules. `{}`
matches every message. Rule field names are case-sensitive.

## Available predicates

All populated fields and combinators in the same object are ANDed. Within each
list-valued leaf, alternatives are ORed. In particular,
`"subject_contains": ["invoice", "urgent"]` means either substring, not both.

| Key | Value | Match condition |
| --- | --- | --- |
| `subject_contains` | String array | Any value occurs in the subject, case-insensitively. |
| `subject_regex` | String array | Any regular expression searches successfully in the subject, case-insensitively. Use anchors for whole-string matching. |
| `to_contains` | String array | Any value occurs in any parsed **To** address, case-insensitively. |
| `to_emails` | String array | Any value exactly equals any parsed To address, case-insensitively. |
| `from_contains` | String array | Any value occurs in any parsed From address, case-insensitively. |
| `from_emails` | String array | Any value exactly equals any parsed From address, case-insensitively. |
| `from_domains` | String array | Any value exactly equals a From address's domain, case-insensitively. `example.com` does not include `sub.example.com`; no wildcard expansion. |
| `attachments_mime` | String array | Any attachment content type matches any case-insensitive glob. Supports `*`, `?`, `[seq]`, `[!seq]`; for example `image/*`. A nonempty constraint fails when no matching attachment exists. |
| `headers_equals` | Object of header name → string | Every named header exists and exactly equals its expected value. Names are case-insensitive; values are case-sensitive. |
| `headers_contains` | Object of header name → string | Every header value contains its corresponding substring, case-insensitively. |

The metadata comes from the parsed email before pipeline transforms: trimmed,
lowercase subject; trimmed, lowercase To/From addresses; their sender domains;
lowercase header names with trimmed values; and trimmed, lowercase attachment
content types. To predicates do not inspect Cc, Bcc, display names, or SMTP
envelope recipients. No body, attachment filename/size/count, mailbox, date, or
arbitrary-JsonLogic predicate is implemented. Headers can be used only through
the two header predicates; they do not become dedicated address matchers.
Negating `attachments_mime: ["*/*"]` excludes typical MIME-typed attachments,
but is not an attachment-count test: missing or malformed content types can
escape that pattern.

## Boolean composition

| Key | Value | Condition |
| --- | --- | --- |
| `all` | Array of child rule objects | Every child matches. |
| `any` | Array of child rule objects | At least one child matches; **an empty array means no constraint and is true**. |
| `none` | Array of child rule objects | No child matches. |
| `negate` | One child rule object | Child does not match. Omit, or use `null`, for no negation. |

Combinators may nest. Empty leaf arrays, empty header maps, empty `all`, empty
`any`, and empty `none` all impose no constraint. An empty child object is true:
`{"any":[{}]}` is true, while `{"none":[{}]}` and `{"negate":{}}` are false.
Do not add empty placeholder branches to an intended restrictive rule.

Example: require both subject terms, require a PDF, accept either of two sender
domains, and exclude a specific sender:

```json
{
  "from_domains": ["vendor.example", "billing.example"],
  "attachments_mime": ["application/pdf"],
  "all": [
    {"subject_contains": ["invoice"]},
    {"subject_contains": ["approved"]}
  ],
  "none": [
    {"from_emails": ["sandbox@vendor.example"]}
  ]
}
```

## Normalization and acceptance traps

Author clean canonical values yourself; accepting JSON is weaker than validating
the intended predicate.

- Top-level `to_contains`, `from_domains`, `subject_contains`, and
  `attachments_mime` are trimmed and lowercased; blank entries disappear.
  Duplicates remain. Scalars are permissively wrapped, but use arrays.
- Top-level `subject_regex`, `to_emails`, `from_contains`, and `from_emails`
  preserve whitespace and order. Case-insensitive comparison does not remove
  accidental spaces. Regex contents must retain their intended case/escapes;
  double JSON backslashes, for example `"\\bINV-[0-9]+\\b"`.
- Top-level header maps trim/lowercase names and trim values. Invalid non-object
  header input is silently converted to `{}`. Use proper string maps and do not
  rely on coercion.
- Child rules under the combinators are not recursively validated/normalized
  during request parsing. Always supply child
  objects with canonical arrays/maps, trim values explicitly, and compile/test
  the whole rule. Malformed children may pass API parsing and fail later or
  silently remove constraints.
- Unknown keys can be retained but are ignored during matching. A
  rule consisting only of misspelled or unsupported keys matches everything.
  Use the exact plural names `headers_equals` and `headers_contains`;
  singular shorthand is not reliable route configuration.
- Empty strings are dangerous: `headers_contains` with an empty expected value
  also passes for a missing header. An empty regex matches every subject; an
  empty `from_contains` substring matches any available sender. Use an explicit
  empty rule only when match-all is intended.
- Regex search sees the normalized lowercase, trimmed subject. Invalid patterns
  and guarded regex failures/timeouts do not match; a nonempty list of only
  invalid regexes is false, not match-all. Risky patterns use the bounded regex
  helper. The UI lints top-level `subject_regex` on save; ordinary route API
  creation does not establish regex validity. Prefer simple patterns and verify
  representative matching and nonmatching subjects.

## Verification

For each authored rule, check allowed keys recursively, compile it, and test at
least one intended match, one intended rejection, and relevant missing-field
cases using real parsed-email metadata. Verify OR alternatives and AND
requirements separately. Pipeline preview alone does not test route matching.
