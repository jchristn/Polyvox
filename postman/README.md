# Polyvox for Postman

## Drag-and-drop import

1. In the Postman desktop app, click **Import** and drag in both files:
   - [Polyvox.postman_collection.json](Polyvox.postman_collection.json)
   - [Polyvox.local.postman_environment.json](Polyvox.local.postman_environment.json)
2. Select **Polyvox - Local** in the environment selector.
3. Set `base_url` (default `http://127.0.0.1:8000`). If the server requires a bearer
   token, set the local `api_token` value; the exported token is intentionally empty.
4. Set **Settings > General > Working directory** to the project root so the
   bundled file `tests/fixtures/jfk.wav` can be read. Alternatively select your
   file in **Body > form-data > file**. A file import does not include its audio.
5. Start Polyvox with `docker compose up --build`, send **Service status > Readiness**,
   then use **Transcribe your audio**.

These are standard **Collection v2.1 JSON** and **environment JSON** exports.
You do not need to import YAML, install the CLI, or regenerate requests from
OpenAPI. The collection includes documentation, request descriptions, saved
response examples, inherited bearer authentication, and response assertions.

## Editable variables

Postman syntax is `{{variable}}` with double braces. The environment supplies:

| Variable | Use |
| --- | --- |
| `base_url` | Local, staging, or production service origin |
| `api_token` | Service bearer token; empty for an unauthenticated server |
| `audio_file` | File for your editable transcription requests |
| `output_format` | `text`, `json`, `jsonl`, or `sse` for the configured-output request |
| `diarization` | `true` / `false` for speaker labels |
| `include_audio` | `true` / `false` for base64 WAV clips; text forces false |
| `fixture_audio_file` | Known speech input for regression checks |
| `invalid_audio_file` | Intentionally invalid input for error checks |
| `expected_text` | Expected fixture word in regression checks |
| `expected_language_prefix` | Expected fixture language in regression checks |

Collection defaults also exist; the selected environment takes precedence.
Use local/private values for credentials and do not re-export real tokens.
If the app asks you to reselect a local file, use the file picker. Selecting a
file can replace its variable with a fixed path in that request.

The collection has **30 requests** in three folders: **Service status**,
**Transcribe your audio**, and **Acceptance suite**. The first two are for everyday
use. The 21 acceptance scenarios preserve their option combinations to test the
contract independently of your exploratory settings. They perform real inference
and call `/clear-models`, so run them sequentially on an idle test instance.

[DOCUMENTATION.md](DOCUMENTATION.md) is embedded in the collection's documentation
panel. It covers options, formats, segment/audio fields, stream completion,
authentication, error handling, and recovery. Saved responses show shortened
single-segment excerpts from actual fixture inference; the WAV clip matches
that segment. [openapi.yaml](../openapi.yaml) remains the API contract.

## Optional CLI verification

From the project root, with the service running:

```bash
postman collection run postman/Polyvox.postman_collection.json \
  --environment postman/Polyvox.local.postman_environment.json \
  --working-dir . --no-insecure-file-read \
  --timeout-request 120000 --no-report-events
```

Override a value with `--env-var base_url=http://127.0.0.1:8001` if needed.
A full run expects **30 requests and 129 passing assertions**.
Run only the fixed checks with `-i 'Acceptance suite'`. Their expected result is
21 requests and 93 passing assertions. Repeat with and without server/token
authentication. Intentional 400/401/422 responses pass when correctly asserted.
Postman validates the completed stream; pytest separately checks incremental
emission, cancellation, and backpressure. No cloud publication is required.

## Maintaining the exports

The existing `collections/Polyvox` v3 files retain the regression requests and
scripts; they are internal source files for the export, not the app import.
`scripts/export_postman.py` combines them with the editable requests, variable
definitions, documentation, and example fixture. Regenerate both JSON files after
changing those sources:

```bash
uv run --no-sync python scripts/export_postman.py
uv run --no-sync python scripts/export_postman.py --check
uv run --no-sync pytest tests/test_contract.py -q
```

Keep credentials out of generated artifacts. The export check and contract tests
ensure that checked-in JSON remains current and covers the API. Existing v3 CLI
users may continue running `collections/Polyvox` with
`environments/local.environment.yaml`; app users should use the two JSON files above.
