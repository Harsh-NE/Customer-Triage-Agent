# Faithfulness judge

_Generated 2026-11-16 11:51 by `python -m triage.eval.judge`. Generator: `?`; judge: `gemini:gemini-3.5-flash-lite`._

```json
{
  "judged": 19,
  "judge_errors": 0,
  "faithfulness_mean": 0.926,
  "unsupported_rate": 0.316,
  "fully_supported_rate": 0.684,
  "relevance_mean": 1.0,
  "unsafe_rate": 0.0
}
```

## By tier

| tier | n | faithfulness | unsupported | relevance | unsafe |
|---|---|---|---|---|---|
| kb | 19 | 0.926 | 0.316 | 1.0 | 0.0 |

## Replies with an unsupported claim

- **S01#1** (kb, faithfulness 0.75): unsupported: Confirm you can successfully run `docker pull` without receiving a 429 response code or pull rate limit error message.
- **S03#1** (kb, faithfulness 0.75): unsupported: Confirm you can successfully run `docker pull` without receiving a 429 response code or pull rate limit error message.
- **S04#1** (kb, faithfulness 0.8): unsupported: Confirmation is achieved when the Docker System Status Page shows services as operational and image pulls complete successfully without returning the 500 error.
- **S06#1** (kb, faithfulness 0.8): unsupported: Confirm that DNS lookups and hostname resolution succeed inside the container.
- **S17#1** (kb, faithfulness 0.833): unsupported: To confirm: Confirm that the Docker client successfully connects to the daemon and executes commands without connection errors.
- **S18#1** (kb, faithfulness 0.667): unsupported: Confirm that the conflicting process has released the path or handle so that the resource is no longer busy.
