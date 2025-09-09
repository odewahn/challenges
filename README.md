# Recommended environment variables

```
export MCP_HOME=/root
export CHALLENGES_HOME=/root/challenges
export USER_HOME=/home
```

These should be used in the ``mcp-explorer.yaml` like this:

```
mcp:
  - name: SQLITE
    type: stdio
    url: |-
      uv --directory \
      $MCP_HOME/servers-archived/src/sqlite run mcp-server-sqlite \
      --db-path $USER_HOME/tutorial.db
    api_keys: []
    tools: []
  - name: Observer
    type: stdio
    url: |-
      python -u $CHALLENGES_HOME/observer-mcp.py \
      --log-dir=$USER_HOME
    api_keys: []
    tools: []
```

# ORM MCP Services

```
curl --location 'https://snippet-vector-service.platform.gcp.oreilly.com/api/v1/snippet-vectors/vectors/search/' \
--header 'Content-Type: application/json' \
--data '{"query": "python things", "filters": {"content_ourn": {"allow_tokens": ["urn:orm:book:9781492056348", "urn:orm:book:9781492051374"]}}}'
```
