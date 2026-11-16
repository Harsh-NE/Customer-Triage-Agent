# OCR accuracy on screenshots with known text

_Generated 2026-11-13 21:23 by `python -m triage.eval.ocr_eval`. Synthetic clean terminal text, one font: an upper bound for real screenshots. CER/WER = character/word error rate (lower is better); key line = the line with the error cue._

| set | n | CER mean | CER median | WER mean | key line exact | key line within 10% | ms median | engine |
|---|---|---|---|---|---|---|---|---|
| degraded | 12 | 0.043 | 0.005 | 0.186 | 10/12 | 11/12 | 912 | tesseract |
| shots | 6 | 0.012 | 0.007 | 0.061 | 6/6 | 6/6 | 815 | tesseract |

## Per image

| set | image | CER | WER | key line CER | confidence | ms |
|---|---|---|---|---|---|---|
| shots | rate_limit | 0.005 | 0.077 | 0.000 | 0.901 | 1754 |
| shots | daemon_not_running | 0.000 | 0.000 | 0.000 | 0.929 | 475 |
| shots | permission_denied | 0.025 | 0.083 | 0.000 | 0.848 | 730 |
| shots | port_in_use | 0.030 | 0.067 | 0.000 | 0.89 | 900 |
| shots | desktop_wsl_dialog | 0.004 | 0.046 | 0.000 | 0.939 | 663 |
| shots | secrets | 0.009 | 0.095 | 0.000 | 0.898 | 1246 |
| degraded | rate_limit scale 1.0 blur 0.0 | 0.005 | 0.077 | 0.000 | 0.901 | 813 |
| degraded | rate_limit scale 1.0 blur 0.6 | 0.005 | 0.077 | 0.000 | 0.9 | 803 |
| degraded | rate_limit scale 1.0 blur 1.1 | 0.005 | 0.077 | 0.000 | 0.935 | 838 |
| degraded | rate_limit scale 0.75 blur 0.0 | 0.005 | 0.077 | 0.000 | 0.864 | 926 |
| degraded | rate_limit scale 0.75 blur 0.6 | 0.005 | 0.077 | 0.000 | 0.881 | 905 |
| degraded | rate_limit scale 0.75 blur 1.1 | 0.005 | 0.077 | 0.000 | 0.929 | 816 |
| degraded | rate_limit scale 0.55 blur 0.0 | 0.005 | 0.077 | 0.000 | 0.927 | 1130 |
| degraded | rate_limit scale 0.55 blur 0.6 | 0.005 | 0.077 | 0.000 | 0.904 | 852 |
| degraded | rate_limit scale 0.55 blur 1.1 | 0.063 | 0.385 | 0.060 | 0.768 | 918 |
| degraded | rate_limit scale 0.4 blur 0.0 | 0.024 | 0.077 | 0.000 | 0.888 | 974 |
| degraded | rate_limit scale 0.4 blur 0.6 | 0.015 | 0.077 | 0.000 | 0.894 | 997 |
| degraded | rate_limit scale 0.4 blur 1.1 | 0.377 | 1.077 | 0.398 | 0.403 | 1255 |
