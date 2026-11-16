"""Problem-normalization consistency probe: the same problem in different words should give the same structured signature.
The 42-item paraphrase file has one query per gold issue, so it cannot measure this. These groups were written for this review
(6 problems x 3-4 phrasings, written independently of the ontology and the scenarios); it is a probe, not a benchmark."""
import itertools, json, sys
sys.path.insert(0, "D:/CustomerSupportTriage-Microsoft")
from triage.clarifier import Clarifier
from triage.hybrid import HybridKBRetriever
from triage.understand import extract, load_known_products

GROUPS = {
    "rate limit": ["docker pull fails with 'You have reached your pull rate limit' HTTP 429",
                   "Docker Hub is throttling me, too many pulls, I get a 429 when pulling images",
                   "getting toomanyrequests when I docker pull, says I've hit the pull rate limit",
                   "pulls from hub are blocked: rate limit reached, how do I raise the limit"],
    "daemon not running": ["Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
                           "docker ps says it can't talk to the daemon, is docker even running?",
                           "every docker command fails, the docker daemon doesn't seem to be up on my linux box"],
    "port in use": ["Bind for 0.0.0.0:8080 failed: port is already allocated",
                    "I can't start my container, port 8080 is already in use",
                    "docker run -p 8080:80 fails because something else is using the port"],
    "desktop stuck starting (windows)": ["Docker Desktop is stuck on starting on Windows with WSL 2",
                                         "docker desktop never finishes starting after I installed wsl2 on windows 11",
                                         "Docker Desktop for Windows hangs on Starting the Docker Engine"],
    "socket permission denied": ["permission denied while trying to connect to the Docker daemon socket",
                                 "got permission denied on /var/run/docker.sock when I run docker ps as my user",
                                 "I need sudo for every docker command, how do I run docker without it"],
    "OOM killed": ["container exited with code 137 OOMKilled",
                   "my container keeps getting killed, I think it runs out of memory",
                   "docker inspect shows OOMKilled true and exit code 137"],
}
kb = HybridKBRetriever()
known = load_known_products()
rows = {}
for g, qs in GROUPS.items():
    rows[g] = []
    for q in qs:
        c = Clarifier(None, kb)
        s = c.start()
        r = c.turn(s, q)
        f = extract(q, None, known).fields
        hyps = (r.meta.get("hypotheses") or [])
        if r.signature and r.signature.hypotheses:
            hyps = [{"label": h.label, "weight": round(h.weight, 3)} for h in r.signature.hypotheses[:5]]
        top = [h["label"] for h in hyps[:3]]
        rows[g].append({"q": q, "product": f.product_area, "platform": f.platform, "errors": f.error_messages, "codes": f.error_codes,
                        "canonical": (r.signature.canonical_string if r.signature else None), "top1": top[0] if top else None,
                        "top3": top, "status": r.status.value, "reason": r.reason})
tot = {"pairs": 0, "same_product": 0, "same_top1": 0, "top1_in_other_top3": 0}
for g, rs in rows.items():
    print("=" * 90, "\n" + g)
    for x in rs:
        print(f"  [{x['status']:5}/{x['reason'][:18]:18}] product={x['product']!s:11} platform={x['platform']!s:8} top1={str(x['top1'])[:62]!r}")
    p = s1 = s2 = s3 = 0
    for a, b in itertools.combinations(rs, 2):
        p += 1
        s1 += a["product"] == b["product"]
        s2 += a["top1"] == b["top1"]
        s3 += (a["top1"] in b["top3"]) and (b["top1"] in a["top3"])
    print(f"  pairs={p} same product_area={s1} same top-1 cause={s2} each top-1 within the other's top-3={s3}")
    tot["pairs"] += p; tot["same_product"] += s1; tot["same_top1"] += s2; tot["top1_in_other_top3"] += s3
print("\nTOTAL", json.dumps(tot))
json.dump(rows, open("D:/CustomerSupportTriage-Microsoft/reports/regression/normalization_probe.json", "w"), indent=1, default=str)
