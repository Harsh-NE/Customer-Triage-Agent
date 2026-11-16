# Review of the 13 held-out "gold" labels

Reviewer: Claude (an AI model), not an independent human. For each question I read the full Stack Overflow question and accepted answer from the ticket store, then the KB section the label points to, and checked the chunk text for the specific fact the customer needs. **This is a second opinion on drafts, not human verification**: the notes say `verified=reviewer-confirmed` / `reviewer-weak`, never `verified=True`.

* **confirmed**: the labelled section documents the fix for this exact problem.
* **weak**: right topic and page, but the specific cause or fix is implicit, in an adjacent section, or only half of the answer.
* No label was outright wrong, so none was reclassified. The 52 "KB gap" labels were **not** reviewed and stay `verified=False`.

| id | verdict | reason |
|---|---|---|
| H003 | confirmed | KB 'Connecting to the database' gives `docker exec -it <container> psql -U postgres`, the accepted answer's fix. |
| H006 | confirmed | KB 'Substitute with --env-file' documents choosing a custom env file on the command line (`--env-file`), which is what the asker wants. |
| H028 | confirmed | Accepted answer points to exactly this KB section: put PORT in `.env` for interpolation, not `env_file`. |
| H030 | confirmed | KB 'Requirements' lists the ports that must be open between swarm hosts (the accepted answer's advice). |
| H032 | confirmed | KB 'SSH mounts' documents the recommended way to use an SSH key in a build (`--ssh`) instead of `--build-arg`. |
| H042 | confirmed | KB 'Interpolation > Overview' documents `$$` for a literal dollar sign (verified in the chunk text). |
| H043 | confirmed | KB 'Use Docker Compose to run a database' sets the database host to the Compose service name (verified in the chunk text). |
| H007 | weak | On topic (`--env-file` with `docker run`), but the actual cause here, the option placed after the image name, is not stated in the section. |
| H013 | weak | Same-network container-to-database connection is documented with `docker run --network`; the Compose service-name-as-hostname point is not explicit. |
| H021 | weak | Right page, adjacent section: the fix (`--env-file` for interpolation) is in 'Substitute with --env-file'; the labelled `.env` section only implies it. |
| H034 | weak | The section shows BuildKit and legacy builder output side by side (`DOCKER_BUILDKIT=0` prints 'intermediate container'), but never says BuildKit is now the default or that disabling it restores the old output. |
| H046 | weak | Documents `docker buildx build --platform` (the Docker half of the answer); the Quarkus/GraalVM x86_64 builder-image half is outside Docker's docs. |
| H056 | weak | `host.docker.internal` is the documented way to reach a host service, but this asker's cause is Redis bound to 127.0.0.1, which the section does not mention. |

Consequence for the numbers: the evaluation oracle counts a fix as right only when it cites the single labelled issue, so on the 6 weak labels (and H021, where the better section is the adjacent one) a fix from a neighbouring section is scored wrong. Held-out "resolved" rates are therefore conservative for those items, and the 7 confirmed items are the cleanest signal (n=7: too few for rates).

---

## The 52 "KB gap" labels

Same reviewer, same method: for each, the accepted answer, then the top three KB issues the retriever finds, then a targeted search of the KB text for the specific fact the answer relies on.

**6 were wrong** (the KB does document the fix; the draft said it did not) and are now gold; **46 are confirmed gaps** (none of the KB documents the fix). The gold set is now 19 questions.

| id | new label | why |
|---|---|---|
| H009 | gold, confirmed | KB 'Requirements' lists the ports (2377, 7946, 4789) that must be open between swarm nodes: the accepted answer. The retriever ranked other overlay sections first. |
| H014 | gold, confirmed | KB 'Interpolation > Overview' documents `${VAR:-default}`, the accepted answer's fix. |
| H018 | gold, confirmed | KB host-driver Overview says a container on host networking gets no IP of its own (verified in the chunk text): the accepted answer. |
| H033 | gold, confirmed | KB 'Manage Docker as a non-root user' documents the docker-group steps and re-login. A retrieval MISS: it was not in the top 3. (The ontology wrongly lists this issue as undocumented.) |
| H004 | gold, weak | KB explains that a bind mount hides existing container files (the cause); it does not give the asker's docker-cp workaround. |
| H051 | gold, weak | KB build reference documents `context`/`dockerfile` (relative to the context); the specific mistake in the question is not called out. |

Confirmed gaps that have an *adjacent* KB page (a reader could be sent to the wrong place by it): H010 (history.md (Compose file format versioning)); H036 (azure-pipelines guide (Docker Hub connection, not ACR)); H038 (pruning.md); H045 (image-layers tutorial (docker commit)); H049 (networking-how-tos (host.docker.internal; Desktop only)); H058 (Desktop shared-volume permissions); H059 (testcontainers docs); H060 (compose `sysctls` reference); H067 (persisting-container-data); H069 (glibc vs musl page); H012 (DHI OpenShift guide).

Three findings beyond the labels: (1) H033 and H009 are **retrieval misses on documented issues**, the most useful kind of failure to fix; (2) the ontology marks "docker socket permission denied" as undocumented although `linux-postinstall.md` documents it (to fix in the knowledge-graph step); (3) basic CLI how-tos (restart a container by id, `docker commit`) are not in the KB at all, because the CLI reference is not part of it.
