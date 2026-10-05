"""
demo_corpus.py -- a tiny hand-built KB for offline tests (MockRetriever).

Mirrors the SHAPE of the real Docker KB (heading depth quirks, platform-split sections, a
near-duplicate pair, release-notes noise) so structural logic can be tested without Chroma.
Text is paraphrased for tests; it is NOT a copy of real documentation and its content is not
evidence about Docker. Real-data behaviour is measured by clarifier_eval against the real store.
"""

from __future__ import annotations


def _chunk(cid: str, path: str, article: str, heading: list[str], text: str, **meta) -> dict:
    return {"chunk_id": cid, "source_path": path, "article_title": article, "heading_path": [article, *heading],
            "text": text, "metadata": {"doc_kind": "troubleshooting", **meta}}


HUB = "content/manuals/docker-hub/troubleshoot.md"
TOPICS = "content/manuals/desktop/troubleshoot-and-support/troubleshoot/topics.md"
DAEMON = "content/manuals/engine/daemon/troubleshoot.md"


def demo_corpus() -> list[dict]:
    hub = dict(product_area="docker-hub", component="troubleshoot")
    desk = dict(product_area="desktop", component="troubleshoot-and-support")
    eng = dict(product_area="engine", component="daemon")
    return [
        # near-duplicate pair: issue is the H2, "Error message / Solution" are H3 (the shallow layout)
        _chunk("hub-0001", HUB, "Troubleshoot Docker Hub", ["You have reached your pull rate limit (429 response code)", "Error message"],
               "docker pull fails with a 429 response code.\n```text\nYou have reached your pull rate limit. You may increase the limit by authenticating and upgrading\n```", **hub),
        _chunk("hub-0002", HUB, "Troubleshoot Docker Hub", ["You have reached your pull rate limit (429 response code)", "Solution"],
               "Authenticate or upgrade your Docker account to raise the pull rate limit for docker pull.", **hub),
        _chunk("hub-0003", HUB, "Troubleshoot Docker Hub", ["Too many requests (429 response code)", "Error message"],
               "docker pull fails with a 429 response code when too many requests are sent.\n```text\nToo Many Requests\n```", **hub),
        _chunk("hub-0004", HUB, "Troubleshoot Docker Hub", ["Too many requests (429 response code)", "Solution"],
               "Reduce the abuse rate of requests to Docker Hub docker pull and retry later.", **hub),
        # platform-split sections: issue is the H3 under "Topics for Windows / Mac"; error text lives in the section
        _chunk("desk-0001", TOPICS, "Troubleshoot topics for Docker Desktop",
               ["Topics for Windows", "Docker Desktop fails to start when anti-virus software is installed"],
               "Docker Desktop will not start on Windows when anti-virus software conflicts with Hyper-V.", **desk),
        _chunk("desk-0002", TOPICS, "Troubleshoot topics for Docker Desktop",
               ["Topics for Mac", "Incompatible CPU detected"],
               "Docker Desktop will not start on a Mac with an incompatible CPU. Check kern.hv_support.", **desk),
        _chunk("desk-0003", TOPICS, "Troubleshoot topics for Docker Desktop",
               ["Topics for all platforms", "`port already allocated` errors"],
               "Starting a container fails.\n```console\nBind for 0.0.0.0:8080 failed: port is already allocated\n```", **desk),
        # single clear issue
        _chunk("eng-0001", DAEMON, "Troubleshooting the Docker daemon", ["Daemon", "Unable to connect to the Docker daemon"],
               "```text\nCannot connect to the Docker daemon. Is 'docker daemon' running on this host?\n```\nThe daemon is not running or the client points at another host.", **eng),
        # release-notes noise that should be down-weighted
        {"chunk_id": "rel-0001", "source_path": "content/manuals/desktop/release-notes.md",
         "article_title": "Docker Desktop release notes", "heading_path": ["Docker Desktop release notes", "Bug fixes and enhancements"],
         "text": "Fixed a bug where Docker Desktop would not start on Windows and Mac. Fixed docker pull errors.",
         "metadata": {"doc_kind": "release_notes", "product_area": "desktop", "component": "release-notes"}},
    ]
