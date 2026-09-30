# Custom JSON extraction helpers

Use these helpers inside `map.custom_json` expressions. They return values; they do not add pipeline steps or mutate the message. The complete function allowlist is `transform.html_to_text`, `extract.urls`, `extract.bullet_list`, `extract.reply_segments`, `extract.key_value_pairs`, `extract.tables`, and `extract.dom`. Both `{"call":{"fn":"extract.tables","args":{}}}` and `{"call.extract.tables":{}}` invoke the same helper. Argument values can be DSL expressions.

For every `extract.*` helper, omitted or `null` body arguments fall back to the corresponding `message.html` / `message.text`. Supply `""` to override a body with an empty string. DOM uses HTML only. `transform.html_to_text` has **no implicit message fallback**. Pass actual JSON booleans, numbers, strings, and arrays rather than relying on coercion.

All helpers except reply segmentation have a 200 ms elapsed-time guard. Reply segmentation has its own limits below. Invalid arguments and extraction failures can stop delivery; do not assume helper failures become `null`. Reply, key/value, table, and DOM helpers reject unknown argument keys. HTML-text, URL, and bullet helpers ignore extra keys, which does not make those keys supported options.

## HTML to text

`call.transform.html_to_text` accepts only the useful arguments `html` and `text`; both default to absent. A truthy `text` is returned as a string unchanged. Otherwise a truthy `html` is converted; with neither, the result is `null`. To force HTML conversion, omit `text` or pass `""`.

Conversion preserves links as inline text plus URL, disables line wrapping, compacts whitespace, normalizes line endings, strips zero-width characters, and skips head/script/style/noscript content. Lists become text lines without generated markers. This helper does not expose the underlying converter's `width`, `preserve_links`, `collapse_whitespace`, or `keep_tables` options; use pipeline transform options where applicable, or `extract.tables` for structured cells. Ordinary conversion failure returns `null`; timeout is an error.

## URLs

| Argument | Default and contract |
| --- | --- |
| `html`, `text` | Corresponding message body. |
| `mode` | `"html"` or `"text"`. Without a recognized mode, supplying a `text` key without an `html` key selects text; otherwise HTML. Modes are case-insensitive. |
| `deduplicate` | `false`. Deduplicates the full `(url, title, element)` combination, not just URL. |

Returns an array of objects with `url` and optional `title` / `element`; no matches returns `[]`. Use `vars.links[0].url`, for example. HTML mode returns HTML matches when any exist; otherwise it falls back to text. Text mode ignores HTML. Supplying both sources does not combine them.

HTML extraction reads `href` from `a`, `area`, and `link`; `src` from `script`, `img`, `iframe`, and `source`; `action` from `form`; and `formaction` from `button` and `input`. Anchor text supplies the title; otherwise the HTML `title` attribute is used. `element` is the lowercase tag name. Attribute values can be relative URLs or non-HTTP schemes; this helper does not resolve, fetch, or filter them. It does not extract arbitrary visible HTML URL text, `srcset`, or CSS URLs.

Text extraction recognizes lowercase `http://` / `https://` URLs and Markdown links using those schemes. Markdown targets carry their link label as `title`; bare URLs have no `element` or title. Markdown matches are emitted first, then bare matches outside their spans, so output is not necessarily global text encounter order. Edge whitespace and trailing sentence/closing punctuation are trimmed, including `. , ; : ! ? ) " ] '`. Different titles or elements preserve repeated URLs even with deduplication enabled.

## Bullet and numbered lists

| Argument | Default and contract |
| --- | --- |
| `html`, `text` | Corresponding message body. |
| `mode` | `"html"`; `"html"` / `"text"`, case-insensitive. Unrecognized modes use HTML. |
| `nested` | `false`; retain nested child lists when true. |
| `sanitize` | `true`; remove blank lines from text before grouping. Does not sanitize HTML. |
| `numbered` | `true`; include numbered text lists and HTML `ol`. |

Returns a list of list objects: each has `bullets`, optional `title`; each bullet has `text`, and may have `child` with the same list-object shape. Paths include `vars.lists[0].title`, `.bullets[0].text`, and `.bullets[0].child.bullets`. No matches returns `[]`.

HTML mode extracts top-level `ul` and, when enabled, `ol`; an empty HTML result falls back to text. Its title comes from the preceding nonempty sibling. Nested lists are omitted with `nested:false`, and attached to their parent bullet with `nested:true`; a child list's title is its parent bullet text. Text mode recognizes `- `, `* `, and, when enabled, numeric `1. ` / `1) ` markers. Other symbols and lettered lists are not supported. Indentation establishes nesting, with a tab counting as four spaces. With `nested:false`, indented text items stay in the current flat list. The preceding non-list text line supplies a title. Blank lines split text groups only with `sanitize:false`. Text is whitespace-normalized; multiline continuation paragraphs are not appended to bullets.

## Reply segments

| Argument | Default and contract |
| --- | --- |
| `html`, `text` | Corresponding message body. Each requested source is analyzed independently. |
| `sources` | `["text","html"]`; nonempty array of these exact names, no duplicates. |
| `include_signature` | `false`; emit recognized current-message signatures as separate segments when true. |
| `split_quoted_by_depth` | `false`; split quoted segments on nesting-depth changes when true. |
| `min_confidence` | `0.0`; number in `[0,1]`, filters emitted segments. |
| `max_segments_per_source` | `128`; integer at least 1, clamped to runtime hard cap 128. |
| `max_input_chars_per_source` | `200000`; integer at least 1, clamped to runtime hard cap 200000. |

Returns `text` and `html`. An unrequested source is `null`; a requested missing source returns an empty result object. Each result has `format` (`"text/plain"` or `"text/html"`), `reply_content`, `has_quoted_content`, `max_depth`, `detected_vendors`, and `segments`. Each segment has `kind`, nonnegative `depth`, `content`, `confidence`, `detectors` (ordered strings), and nullable `vendor`.

`kind` is one of `reply_content`, `quoted_header`, `quoted_content`, `forwarded_header`, `forwarded_content`, `signature`. `reply_content` joins the emitted authored-reply segments; it excludes signatures and prior/forwarded messages. Plain-source content is text; HTML-source content contains HTML fragments, not plain text. Use HTML-to-text conversion explicitly if needed. Read `vars.reply.text.reply_content` or iterate `vars.reply.html.segments`. Summary values reflect retained segments after confidence filtering and caps; there is no truncation flag.

Recognition includes quote prefixes/depth, English and Chinese reply/forwarded-message header patterns, signature separators, and template signals for Gmail, Thunderbird, Outlook, Yahoo, Apple Mail, Proton, and Samsung. These are heuristics, not a guarantee that every vendor/language/template is recognized; there is no configurable detector list or vendor selector. Do not depend on a closed set of detector strings.

Default execution limits are 200 ms overall and per requested body, plus 10000 traversed HTML nodes. Time budgets can vary by deployment and are not helper arguments. Input and segment caps truncate retained work; timeout or HTML-node limits raise errors.

## Key/value pairs

| Argument | Default and contract |
| --- | --- |
| `html`, `text` | Corresponding message body; string or `null`. |
| `mode` | `"auto"`; exact `"auto"`, `"html"`, or `"text"`. Auto uses HTML if it yields pairs, otherwise text. Explicit modes use only that source. |
| `separators` | `[":","="]`; nonempty array of distinct single non-whitespace characters. |
| `max_key_words` | `5`; integer at least 1. |
| `allow_prose` | `false`; bypass the prose-token rejection check when true; other key constraints still apply. |
| `allow_html_adjacent_blocks` | `false`; opt into generic adjacent HTML block pairing. |

Returns `items` (ordered accepted pairs), `values` (first value by normalized key), and `groups` (all values by normalized key). Empty result: `{"items":[],"values":{},"groups":{}}`. Each item has `key`, `normalized_key`, `value`, nullable `separator`, `source`, and nullable `line`. Text `line` is one-based; structural HTML has `line:null`. Read `vars.kv.values.order_id`, `vars.kv.groups.order_id`, or iterate `vars.kv.items`.

Keys start with an alphabetic character and contain only letters, digits, whitespace, and hyphens. Whitespace is compacted; lowercase plus whitespace/hyphen-to-underscore normalization creates lookup keys (`Order-ID` becomes `order_id`). Keys exceeding `max_key_words`, invalid/empty values, URL-scheme splits, and candidate lines ending in `?` or `!` are rejected. By default, key tokens `an`, `are`, `can`, `could`, `is`, `me`, `please`, `thanks`, `was`, `were`, `where`, `which`, `would`, `you`, `your` are rejected as prose. Set `allow_prose:true` only when the sender's labels require it.

Text uses the earliest configured separator in each line, strips an initial `- ` / `* ` marker, trims values at their edges and removes one trailing period while preserving internal whitespace. A key ending with a separator and no value can consume the next nonempty line unless that line starts another valid key. It does not assemble arbitrary multiline values.

HTML extracts two-cell table rows, definition lists, labels/form controls, list items, bold/strong key hints, and optionally adjacent blocks; then supplements with HTML-to-text separator lines. Results are text-only. Structural passes run in that order, followed by fallback; `items` is not a universal DOM-order traversal. Structural duplicates are retained, but fallback pairs already seen structurally with the same normalized key/value are omitted. Supported `source` values: `text`, `html_text`, `html_table`, `html_definition_list`, `html_label`, `html_list`, `html_emphasis`, `html_adjacent_block`.

## Tables

| Argument | Default and contract |
| --- | --- |
| `html`, `text` | Corresponding message body; string or `null`. |
| `mode` | `"auto"`; `"auto"`, `"html"`, or `"text"`. Auto combines HTML candidates first, then text candidates. Explicit modes use only that source family. |
| `header_mode` | `"auto"`; `"auto"`, `"first_row"`, `"first_column"`, `"both"`, `"none"`. |
| `include_html_grids` | `false`; opt into non-table HTML grids. |
| `html_grid_mode` | `"strict"`; `"strict"`, `"off"`, `"lenient"`. Grids need `include_html_grids:true` and a mode other than `off`. |
| `min_rows`, `min_columns` | `2` each; integers at least 1, measured against the full matrix including headers. |
| `min_grid_confidence` | `0.75`; number in `[0,1]`, for non-table grids. |
| `max_tables` | `20`; integer at least 1. |
| `max_rows`, `max_columns` | `500`, `50`; integers at least 1, each at least its corresponding minimum. Caps include headers. |
| `deduplicate` | `true`; retain the first occurrence of a cleaned table matrix. |

Returns `tables` and `summary.table_count`. No matches returns `{"tables":[],"summary":{"table_count":0}}`. Supported source formats:

| `source` | Structure |
| --- | --- |
| `text_tsv` | Consecutive tab-delimited lines. |
| `text_pipe` | Markdown-style pipe table with a separator row. |
| `text_ascii` | Boxed ASCII table. |
| `html_table` | Native HTML table. |
| `html_aria_table` | Opt-in ARIA table/grid. |
| `html_css_table` | Opt-in inline CSS display-table structure. |
| `html_repeated_grid` | Opt-in repeated row-like blocks. |
| `html_label_grid` | Opt-in repeated label/value cards. |

Each table has the following complete public shape:

| Field | Meaning / fields below it |
| --- | --- |
| `index`, `source`, `confidence` | Zero-based result index, source format, score in `[0,1]`. |
| `caption` | `null` or `{text, normalized, lookup_key}`. |
| `row_count`, `column_count` | Capped full matrix dimensions. |
| `header_strategy` | Resolved header mode; automatic inference can resolve to `none`. |
| `col_headers`, `row_headers` | Header arrays; each `{index, text, normalized, lookup_key}`. `index` is zero-based matrix position. |
| `header_candidates` | `first_row` and `first_column`, each arrays of the same header objects, even when headers are not selected. |
| `rows` | Each `{index, lookup_key, values, cells}`. `values` maps column keys to strings. |
| `cols` | Each `{index, lookup_key, values, cells}`. `values` maps row keys to strings. |
| `lookup` | `by_row.<row_key>.<column_key>` and `by_column.<column_key>.<row_key>`, both return text. |
| `matrix` | Rectangular array of arrays of strings, including headers; missing cells are `""`. |
| `detection` | `{reason, selector_hint, details}`; selector hint is nullable, details maps diagnostic keys to scalar values. |

Each `rows[*].cells[*]` / `cols[*].cells[*]` item has `row_index`, `column_index`, `row_lookup_key`, `column_lookup_key`, `value`, `row_span`, `col_span`, `span_origin`, and `is_span_origin`. `span_origin` is `null` or `{row_index,column_index}`. Native HTML spans expand into the visual matrix with origin metadata. There is no top-level flattened `cells` array.

Selected header axes are excluded from data `rows`, `cols`, and `lookup`: `first_row` removes the first matrix row, `first_column` removes the first column, and `both` removes both. Headers on unselected axes get synthetic keys. Header keys are entity-decoded, zero-width-stripped, trimmed, case-folded, and normalized with separator/punctuation runs becoming `_`. Duplicates get `_2`, `_3`, etc.; empty keys use `row_N` / `column_N` beginning at 1 in the selected axis; digit-leading keys get `row_` / `column_` prefixes. Use actual returned `lookup_key`, especially for unfamiliar or colliding labels. Cell text preserves internal whitespace after cleanup; numeric-looking cells remain strings.

HTML candidates precede text, so deduplication normally preserves the HTML version. Layout-only tables, navigation/link groups, hidden content, and insufficient-confidence grids may be rejected; the helper is not a promise to return every visually tabular block. Use `lenient` only for a tested sender template. These configurable table caps have no separate declared maximum, but the shared time guard still applies. Results do not expose a truncation flag.

## DOM selectors and records

Use `call.extract.dom` for stable HTML templates, scalar selectors, or repeated records that table/key-value heuristics cannot reliably describe. It supports CSS and XPath selectors; it is not a browser and does not execute JavaScript or compute external stylesheets.

| Argument | Default and contract |
| --- | --- |
| `html` | `message.html`; string or `null`. |
| `selector_type` | Required: `"css"` or `"xpath"`. |
| `selector` | Required nonblank selector string, edge-trimmed. XPath must return only element nodes. |
| `value` | Required: `"text"`, `"attr"`, `"html"`, `"outer_html"`, `"exists"`, or `"count"`. Required even for structured records. |
| `attr` | `null`; required for `value:"attr"`. Safe attribute name, see below. |
| `many` | `false`; scalar mode retains the first projected value/item, true retains all up to the cap. Does not limit structured container records. |
| `max_matches` | `16`; integer 1–32; limits top-level matches and each structured field's matches. |
| `default` | `null`; string, number, boolean, or `null`; scalar fallback when no non-null projection exists. No object/array defaults. |
| `required` | `false`; error when a selector has no matches on nonblank HTML. |
| `normalize_whitespace` | `true`; compact whitespace and remove zero-width characters for text projection. False preserves parser text whitespace. |
| `fields` | `null`; nonempty object of field configs for structured record extraction. |
| `include_container` | `null`; structured-only object with `tag:false` and `attrs:[]` defaults. |

Scalar mode returns `value` (first non-null projection or default), `values`, `item`, `items`, and `summary`. Each match item has `{index,tag,value,text,attrs}`. `text` is always normalized diagnostic text even if projection normalization is disabled. `attrs` includes available safe attributes. `summary` has `match_count` (retained matches up to cap), `value_count` (non-null projected values before `many` reduces the result), and `truncated`. `many:false` retains at most one `values` entry and one item; it still projects retained matches. Thus a first match lacking the requested attribute can yield `item.value:null` while top-level `value` comes from a later match. Empty strings are valid projections, so they do not trigger a default.

`text` projects element text; `attr` returns the selected attribute or `null`; `html` returns inner markup and `outer_html` includes the matched element. `exists` / `count` return a boolean / integer in `value`, with empty `values` and `items`, `item:null`, and `summary.value_count:0`. Count is capped by `max_matches`, not an unlimited total. Use these modes rather than XPath `count(...)`, `string(...)`, `text()`, or `@href`, which return non-element results and are rejected.

With `fields`, top-level matches are record containers. Field names must match `^[A-Za-z_][A-Za-z0-9_]*$`. Each field config accepts exactly `selector` and `value` (required), plus `selector_type`, `attr`, `many`, `default`, `required`, `normalize_whitespace` with the same meanings/defaults as above. `selector_type` inherits the parent and, if supplied, must match it. Fields do **not** accept `fields`, `max_matches`, `html`, or `include_container`; arbitrary recursive record configs are unsupported. CSS selectors run beneath the container. XPath fields must be relative, normally `.//...`; leading `/` or `//` is rejected. Keep all field selectors local to the intended container rather than using upward or document-wide traversal.

Structured output retains every container up to `max_matches`, regardless of top-level `many`. Top-level `value:null`, `values:[]`; `item` is the first record and `items` contains all records. `summary` has only `item_count` and `truncated`. Each record contains `index`, `values` (first/aggregate/default value per field), and `fields` (detailed result per field). Each detailed field result has `value`, `values`, `match_count`, `value_count`, and `truncated`. A field with `many:true` still places its first value in record `values`; use `items[0].fields.<name>.values` for the array. Top-level scalar projection controls do not replace field-specific options.

`include_container` accepts only `tag` (boolean) and `attrs` (array of unique safe attribute names). Requested present attributes and the optional tag are added to each record. Unrequested tag and empty attrs are omitted. Attribute names must match `^[A-Za-z_][A-Za-z0-9_.:-]*$`, contain no surrounding whitespace, and must not start with `on` case-insensitively. `include_container.attrs` additionally disallows `style`. These are name restrictions, not URL or HTML sanitization; scalar `attr:"style"` remains allowed.

Cleanup removes comments, head/script/style/noscript, and elements explicitly hidden by `hidden`, `aria-hidden="true"`, or inline display-none, hidden/collapse visibility, or zero opacity. Raw markup projections represent the cleaned parsed DOM and can retain other attributes; do not treat them as safe rendered HTML. Input is capped at 200000 characters; each raw HTML projection at 8192 characters. `truncated` covers input, excess matches, and raw projection caps; structured summaries also combine field truncation. Choosing `many:false` alone does not set truncation.

On nonblank HTML, `required:true` checks element matches, not a nonempty projected value: empty matched elements and missing attributes still satisfy it. Missing/blank HTML returns the empty envelope before selector execution, even with `required:true`; scalar `value` is `default` (including for `count` / `exists`), while structured `value` is `null`. Test absent-body cases explicitly. Invalid selector syntax, mixed selector engines, non-element XPath results, or unmatched required fields on a retained record raise errors.
