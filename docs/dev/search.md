## Methods of search

PeeringDB has 3 areas where searches are processed:

### 1. The quick search

This search occurs through the top search bar on the PeeringDB website.

**Autocomplete (typeahead):** Triggered while the user types (without pressing Enter). Handled by `request_api_search` in `views.py`, which calls `autocomplete_v2()` in `search_v2.py`. Uses an Elasticsearch `search_as_you_type` field (`auto_suggest`) indexed across `name`, `aka`, `name_long`, and for networks `irr_as_set` and `AS<asn>` variants.

**Full search (on Enter):** Handled by `request_search` in `views.py`, which calls `search_v2()` in `search_v2.py`. Queries Elasticsearch across `fac`, `ix`, `net`, `org`, `campus`, and `carrier` indexes.

Search document definitions and field mappings are in `peeringdb_server/documents.py`.

### 2. REST API filtering

REST API filtering happens when filter parameters are passed to REST API list retrievals.

This is almost a straight pass through to django query set filters (after some sanitizing of course).

Most querying logic for this is defined in `rest.py`

Note that there is some extra effort involved for more intricate query filters, such as relationship queries or customized queries like the `whereis` filter for `ixpfx`

These more complex querying behaviors should be implemented in `serializers.py` through the `prepare_query` method on the serializer.

#### `name_search` filter

The `name_search` filter uses `search_v2()` from `search_v2.py` to find matching entity ids via Elasticsearch, then filters the queryset to those ids.

### 3. Advanced search

The advanced-search UI is wired directly to the REST API, so whatever the REST api is capable of the advanced-search UI can make use of.

New form elements should be added as necessary.

## Elasticsearch index settings

Shard and replica counts for all 6 search indexes (`org`, `fac`, `ix`, `net`, `campus`, `carrier`) are configured in one place, `ELASTICSEARCH_DSL_INDEX_SETTINGS` in `mainsite/settings/__init__.py`, and are tunable per environment:

| Env var | Default | Notes |
|---|---|---|
| `ELASTICSEARCH_NUMBER_OF_SHARDS` | `1` | |
| `ELASTICSEARCH_NUMBER_OF_REPLICAS` | `1` | Set to `0` on single-node clusters |
| `ELASTICSEARCH_USER` | `elastic` | Paired with `ELASTIC_PASSWORD` |
| `ELASTICSEARCH_VERIFY_CERTS` | `false` | Enable where ES presents a cert the app trusts |

django_elasticsearch_dsl applies these to every registered document, so they take effect on every index create — including `pdb_search_index --rebuild`. Do **not** add a `settings` dict to the `class Index` blocks in `documents.py`: the global dict is merged on top of it, so a per-document value is silently ignored.

`number_of_replicas` defaults to `1` so that each primary shard has a copy on another node. With `0`, losing the single node holding a shard takes `/search` down completely. Green cluster health requires at least 2 ES data nodes; a single-node cluster (dev, CI) reports yellow index health with replicas enabled, which is why `dev.py` and `run_tests.py` set it to `0`. Search itself works in either state.
