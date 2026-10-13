# End-to-end evaluation (Clarifier -> Resolver)

_Generated 2026-10-13 12:21 by `python -m triage.eval.e2e_eval`._

Real stores, simulated customer, oracle feedback (see the module docstring). 29 same-author scenarios and thresholds that are starting guesses: this shows how the pieces fit, not quality.

```json
{
  "meta": {
    "retriever": "hybrid",
    "resolver_llm": "gemini",
    "resolver_model": "gemini-3.5-flash-lite",
    "seconds": 626.2,
    "scenario_file": "triage\\eval\\heldout_scenarios.jsonl",
    "llm_calls": 91,
    "input_tokens": 84859,
    "output_tokens": 4989,
    "cost_usd": 0.0379,
    "llm_latency_ms_p50": 3032.8,
    "llm_latency_ms_p95": 4389.32
  },
  "summary": {
    "scenarios": 65,
    "with_gold": 13,
    "out_of_scope": 0,
    "no_gold_other": 52,
    "gold_resolved_rate": 0.231,
    "gold_first_attempt_rate": 0.231,
    "gold_escalated_rate": 0.769,
    "wrong_fix_sent_rate_gold": 0.154,
    "oos_resolved_rate": null,
    "oos_fix_sent_rate": null,
    "oos_escalated_or_rejected_rate": null,
    "no_gold_other_fix_sent_rate": 0.038,
    "kb_gap": 52,
    "kb_gap_kb_fix_sent_rate": 0.019,
    "kb_gap_any_fix_sent_rate": 0.038,
    "first_fix_tier": {
      "tickets": 2,
      "kb": 5
    },
    "mean_questions": 1.88,
    "outcomes": {
      "escalated": 60,
      "resolved": 3,
      "rejected": 2
    }
  }
}
```

| id | opening | outcome | q | fixes sent (tier: gold?) | first fix cites |
|---|---|---|---|---|---|
| H001 | `docker-compose up` vs. `docker compose up` with | escalated/LOW_EVIDENCE | 2 | - | - |
| H002 | Docker PHP with Xdebug 3 env XDEBUG_MODE doesn't | escalated/LOW_EVIDENCE | 2 | - | - |
| H003 | How to get into psql of a running postgres conta | escalated/RETRY_EXHAUSTED | 1 | tickets:no, kb:no | T-5a610c41ca4a |
| H004 | With Docker, how can I bind mount but also prese | escalated/LOW_EVIDENCE | 3 | - | - |
| H005 | Need help setting up golang dockerfile. I'm havi | escalated/LOW_EVIDENCE | 2 | - | - |
| H006 | docker-compose env file set by command line. So  | resolved | 1 | kb:yes | Substitute with `--env-file` |
| H007 | How to pass through environment variables in doc | escalated/LOW_EVIDENCE | 1 | - | - |
| H008 | How to install composer dependencies in a contai | escalated/LOW_EVIDENCE | 3 | - | - |
| H009 | Docker Swarm Overlay Network Not Working Between | escalated/LOW_EVIDENCE | 2 | - | - |
| H010 | ERROR: Version in "./docker-compose.yml" is unsu | escalated/LOW_EVIDENCE | 0 | - | - |
| H011 | Docker: Cannot pull an image that was pushed to  | escalated/LOW_EVIDENCE | 3 | - | - |
| H012 | How do you run an Openshift Docker container as  | escalated/LOW_EVIDENCE | 1 | - | - |
| H013 | Docker Connecting PHP container to MySQL. I have | resolved | 1 | kb:yes | Connect to a containerized database from another container |
| H014 | Docker Compose optional extra_hosts entry from E | escalated/LOW_EVIDENCE | 3 | - | - |
| H015 | Adding PHP Extensions using Docker Compose. I'm  | escalated/LOW_EVIDENCE | 2 | - | - |
| H017 | Slow postgresql startup in docker container. We  | escalated/LOW_EVIDENCE | 3 | - | - |
| H018 | My Docker container does not have IP address. Wh | escalated/RETRY_EXHAUSTED | 1 | kb:no, kb:no | Internal network access (container-to-container) |
| H020 | Trying to add support for Docker to existing Nex | escalated/LOW_EVIDENCE | 1 | - | - |
| H021 | Why is my .env.local not recognized by docker-co | escalated/RETRY_EXHAUSTED | 1 | kb:no | Use the `env_file` attribute |
| H022 | Docker-Compose: Service xxx depends on service x | escalated/LOW_EVIDENCE | 1 | - | - |
| H023 | Docker build: read-only file system. I'm using a | escalated/LOW_EVIDENCE | 3 | - | - |
| H025 | Docker push "Missing image name"-error when push | escalated/LOW_EVIDENCE | 2 | - | - |
| H026 | How to restart container using container-id?. I  | escalated/LOW_EVIDENCE | 3 | - | - |
| H027 | failed to start daemon: Error initializing netwo | escalated/LOW_EVIDENCE | 1 | - | - |
| H028 | How to get port of docker-compose from env_file? | escalated/LOW_EVIDENCE | 1 | - | - |
| H030 | Unable to access ports from services across node | escalated/LOW_EVIDENCE | 1 | - | - |
| H031 | Not able to start `django` project in local as w | escalated/LOW_EVIDENCE | 1 | - | - |
| H032 | How to correctly pass ssh key file from Jenkins  | escalated/LOW_EVIDENCE | 2 | - | - |
| H033 | Running docker without sudo on Ubuntu 14.04. I a | escalated/LOW_EVIDENCE | 3 | - | - |
| H034 | Docker Build missing intermediate layers in cons | escalated/LOW_EVIDENCE | 3 | - | - |
| H035 | How to run Puppeteer and Node.js inside a Docker | escalated/LOW_EVIDENCE | 2 | - | - |
| H036 | How to create Azure Devops Service Connection Do | escalated/LOW_EVIDENCE | 3 | - | - |
| H037 | Docker-Compose file has yaml.scanner.ScannerErro | escalated/LOW_EVIDENCE | 2 | - | - |
| H038 | Why is docker image eating up my disk space that | escalated/LOW_EVIDENCE | 3 | - | - |
| H039 | Cannot run executables with Alpine and Busybox d | escalated/LOW_EVIDENCE | 1 | - | - |
| H040 | Golang distroless Docker exec failed: No such fi | escalated/RETRY_EXHAUSTED | 2 | tickets:no, tickets:no | T-b235b4645a98 |
| H041 | Use private docker registry with Authentication  | escalated/LOW_EVIDENCE | 2 | - | - |
| H042 | How can I escape a $ dollar sign in a docker com | escalated/LOW_EVIDENCE | 3 | - | - |
| H043 | Docker Compose with PHP, MySQL, nginx connection | escalated/LOW_EVIDENCE | 1 | - | - |
| H044 | List all files in Build Context and/or in WORKDI | escalated/LOW_EVIDENCE | 2 | - | - |
| H045 | Docker - how to add new python dependencies to t | escalated/LOW_EVIDENCE | 3 | - | - |
| H046 | Building quarkus native Linux/amd64 (x86_64) ima | resolved | 1 | kb:yes | Simple multi-platform build using emulation |
| H047 | Docker fails with "failed to start containerd: t | escalated/LOW_EVIDENCE | 2 | - | - |
| H048 | Docker install failing in linux with error [Errn | escalated/LOW_EVIDENCE | 1 | - | - |
| H049 | connect: cannot assign requested address. I have | escalated/LOW_EVIDENCE | 1 | - | - |
| H050 | Docker Compose circular container linking. I'm i | escalated/LOW_EVIDENCE | 1 | - | - |
| H051 | docker-compose build error when using parent dir | escalated/LOW_EVIDENCE | 2 | - | - |
| H052 | python install without pip on ubuntu. I need to  | escalated/LOW_EVIDENCE | 3 | - | - |
| H053 | How to retrieve password from docker credStore?. | escalated/LOW_EVIDENCE | 1 | - | - |
| H054 | Traefik v2: 404 while routing HTTP traffic globa | rejected/OUT_OF_SCOPE | 1 | - | - |
| H055 | RedisInsight Docker displaying: site cannot be r | escalated/LOW_EVIDENCE | 1 | - | - |
| H056 | Not able to connect with host interface service  | escalated/LOW_EVIDENCE | 3 | - | - |
| H057 | AWS beanstalk environment isn't rotating docker  | escalated/LOW_EVIDENCE | 3 | - | - |
| H058 | Docker EACCES permission denied mkdir. My friend | escalated/LOW_EVIDENCE | 1 | - | - |
| H059 | Testcontainer error: Could not find a valid Dock | escalated/LOW_EVIDENCE | 1 | - | - |
| H060 | Cannot run sysctl command in Dockerfile. | escalated/LOW_EVIDENCE | 2 | - | - |
| H061 | Gitlab CI/CD Error failed to pull image "python  | escalated/LOW_EVIDENCE | 1 | - | - |
| H062 | EBUSY: resource busy or locked in Docker when tr | escalated/LOW_EVIDENCE | 3 | - | - |
| H063 | Kubernetes: Docker pod starting fails except one | escalated/LOW_EVIDENCE | 3 | - | - |
| H064 | ADD failed : No such file/Directory while buildi | escalated/LOW_EVIDENCE | 3 | - | - |
| H065 | setting up docker permission to VSTS agent in a  | escalated/LOW_EVIDENCE | 3 | - | - |
| H066 | nuxt: not found inside docker image. I am buildi | escalated/LOW_EVIDENCE | 3 | - | - |
| H067 | postgresql container not starting: chmod: changi | escalated/LOW_EVIDENCE | 1 | - | - |
| H069 | Alternative to openjdk:8-alpine for Kafka Stream | rejected/OUT_OF_SCOPE | 1 | - | - |
| H070 | Running django app with docker, unrecognized run | escalated/LOW_EVIDENCE | 2 | - | - |
