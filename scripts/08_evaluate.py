"""
08_evaluate.py -- Recall@5 / Recall@10 over a hand-built set of realistic support queries.

Each query is a paraphrase of a genuine customer complaint, hand-written from a real
article's Symptoms section, with the article's rel_path recorded as ground truth (spot-check
any of them against data/processed/chunks_metadata.jsonl).

Queries fall into two kinds of group, and results are reported for each separately:
  - "distinctive"     -- the article has little competing content in the KB (rare topic).
                          Easy by construction; recall here tends to look artificially high.
  - a named cluster (e.g. "modern_authentication", "bitlocker_tpm", "hcw_error_codes") --
    several near-duplicate sibling articles share the same broad topic and heavy vocabulary
    overlap (found via scripts/08_evaluate.py's cluster discovery over cleaned_docs.jsonl
    titles). These are the realistic, hard case: the retriever has to tell siblings apart,
    not just find the general topic -- this is where retrieval quality actually gets tested.

For each of BM25 and vector search, this measures recall in two modes using the *same*
ranked candidates, so the comparison isolates one variable:
  - "raw"      -- top-K chunks as-is, no dedup (what retrieval looked like before)
  - "expanded" -- top-K distinct parent groups (the "index small, return whole" approach
                  from 07_retrieve.py) -- repeat hits from the same article/section collapse
                  into one slot, freeing room in the top-K for other distinct answers

A hit counts if the query's expected article (rel_path) appears anywhere in the top-K
results for that mode.

Usage:
    python scripts/08_evaluate.py
"""

from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path

from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retrieve = load_module(PROJECT_ROOT / "scripts" / "07_retrieve.py", "retrieve_module")

K_VALUES = (5, 10)
POOL = 50  # raw candidates considered before dedupe/expansion -- generous vs. max(K_VALUES)

# (query, ground-truth rel_path, group). group="distinctive" -> rare topic, little
# competition. Any other group name is a cluster: several sibling queries below share
# that same group, targeting near-duplicate articles on the same broad topic -- these are
# the queries that actually test whether retrieval can discriminate, not just find topic.
QUERIES = [
    # --- distinctive: rare topics, little competing content (original baseline set) ---
    ("We're running Exchange Setup with /PrepareSchema to update our hybrid environment's "
     "AD schema and it fails with an error about a hybrid deployment with Office 365 already existing.",
     "Exchange/ExchangeHybrid/administration/error-when-running-setup-prepareschema.md",
     "distinctive"),
    ("A customer sent an email with an attachment but the recipient never got it, and the "
     "message tracking logs show a transient exception.",
     "Exchange/ExchangeServer/mailflow/failed-to-process-message-due-to-transient-exception.md",
     "distinctive"),
    ("We can't find the federation certificate thumbprint when trying to update our federation trust.",
     "Exchange/ExchangeServer/administration/federation-certificate-with-thumbprint-cannot-be-found.md",
     "distinctive"),
    ("DNS name resolution fails with a WSAHOST_NOT_FOUND 11001 error only when a previous "
     "lookup used the IPv6 address family.",
     "support/windows-server/networking/getaddrinfo-fails-error-11001-call-af-inet6-family.md",
     "distinctive"),
    ("Users logging into RD Web Access with a domain account can't see any of the RemoteApp "
     "programs published on the RD Session Host.",
     "support/windows-server/remote/cannot-view-remoteapp-rd-session-host.md",
     "distinctive"),
    ("Our Azure VM boot diagnostics screenshot shows Windows Update stuck in progress and "
     "failing with error C01A001D.",
     "support/azure/virtual-machines/windows/windows-update-installation-capacity.md",
     "distinctive"),
    ("A pod in our AKS cluster fails to mount a PersistentVolumeClaim that references an "
     "Azure file share.",
     "support/azure/azure-kubernetes/storage/fail-to-mount-azure-file-share.md",
     "distinctive"),
    ("When our laptop is docked with external monitors and the lid is closed, the external "
     "monitor doesn't work.",
     "support/windows-client/shell-experience/docked-external-monitor-not-working-windows-10-1703.md",
     "distinctive"),
    ("Devices plugged into a Thunderbolt dock -- keyboard, mouse -- stop working after Fast "
     "Startup is enabled on Windows 10 or 11.",
     "support/windows-client/setup-upgrade-and-drivers/devices-connected-via-thunderbolt-dock-not-work.md",
     "distinctive"),
    ("SQL Server Windows authentication fails with 'the login is from an untrusted domain "
     "and can't be used with Windows authentication.'",
     "support/sql/database-engine/connect/local-security-subsystem-errors.md",
     "distinctive"),
    ("After moving the msdb database to a new SQL Server instance, users are getting "
     "permission errors.",
     "support/sql/database-engine/security/fix-permission-issues-move-msdb.md",
     "distinctive"),
    ("Outlook won't send or receive email and keeps showing a metered connection warning.",
     "Outlook/classic-outlook-for-windows/profiles-and-accounts/metered-connection-warning.md",
     "distinctive"),
    ("Creating a new Outlook profile fails with 'the connection to Microsoft Exchange is unavailable.'",
     "Outlook/classic-outlook-for-windows/connectivity/connection-issues-mapi-disabled.md",
     "distinctive"),
    ("Installing Microsoft Dexterity Shared Components fails saying another version of the "
     "product is already installed.",
     "support/dynamics/gp/fail-to-install-dexterity-shared-components.md",
     "distinctive"),
    ("Recurring agreement work orders aren't being generated on the expected date in "
     "Dynamics 365 Field Service.",
     "support/dynamics-365/field-service/work-order/agreement-work-orders-not-generated.md",
     "distinctive"),
    ("Testing a mailbox in Dynamics 365 fails with 'mailbox doesn't have email server profile.'",
     "support/power-platform/dataverse/email-exchange-synchronization/mailbox-does-not-have-email-server-profile.md",
     "distinctive"),
    ("Requests routed by our Application Request Routing (ARR) server through a proxy to a "
     "back-end server on another network are being rejected.",
     "support/developer/webapps/iis/application-request-routing/proxy-server-rejects-back-end-requests.md",
     "distinctive"),
    ("A hybrid Microsoft Entra joined Windows device enrolled in Intune shows a policy "
     "update error after running gpupdate /force.",
     "support/mem/intune/device-enrollment/windows-failed-to-apply-mdm-policy.md",
     "distinctive"),
    ("Signing into an Azure app gives error AADSTS7000110, request is ambiguous with "
     "multiple application identifiers found.",
     "support/entra/entra-id/app-integration/error-code-aadsts7000110-request-is-ambiguous.md",
     "distinctive"),
    ("Tenant users on the Windows Azure Pack site don't see the VM templates list in "
     "System Center VMM.",
     "support/system-center/vmm/vm-templates-list-missing.md",
     "distinctive"),
    ("A user can't share a folder or break permission inheritance in SharePoint Online or "
     "OneDrive for Business.",
     "SharePoint/SharePointOnline/lists-and-libraries/error-share-break-inheritance.md",
     "distinctive"),
    ("Anonymous users accessing files in a SharePoint Online library keep getting an "
     "authentication prompt.",
     "SharePoint/SharePointOnline/sharing-and-permissions/anonymous-users-are-prompted-for-credentials-in-library.md",
     "distinctive"),
    ("We want each Excel workbook to open in its own separate window instead of all "
     "sharing one instance.",
     "Office/Client/excel/force-excel-to-open-new-instance.md",
     "distinctive"),
    ("During Teams screen sharing, the other person's request to take control doesn't show "
     "up on the sharing toolbar.",
     "Teams/teams-conferencing/give-control-doesnt-work-sharescreen.md",
     "distinctive"),
    ("The new Teams desktop app shows no video during meetings on a machine that has the "
     "Nahimic audio driver installed.",
     "Teams/meetings/new-teams-desktop-app-fail-render-video.md",
     "distinctive"),
    ("Success and failure actions on a service-level agreement are firing multiple times "
     "in the Dynamics 365 web client.",
     "support/dynamics-365/customer-service/service-level-agreements/actions-run-multiple-times-client.md",
     "distinctive"),

    # --- cluster: modern_authentication (6 sibling articles in the KB, 4 sampled here) ---
    ("After enabling Modern Authentication, Outlook stopped connecting to the mailbox and "
     "keeps prompting to reconnect.",
     "Exchange/ExchangeHybrid/administration/outlook-does-not-connect-with-modern-authentication.md",
     "modern_authentication"),
    ("We use POP or IMAP in Outlook and since modern authentication was enabled we can't "
     "connect to the mailbox at all.",
     "Exchange/ExchangeOnline/administration/cannot-connect-mailbox-pop-imap-outlook.md",
     "modern_authentication"),
    ("Outlook keeps prompting for a password over and over ever since modern authentication "
     "was turned on for our tenant.",
     "Outlook/classic-outlook-for-windows/authentication/outlook-prompt-password-modern-authentication-enabled.md",
     "modern_authentication"),
    ("Outlook shows as disconnected in the status bar right after we enabled modern "
     "authentication for the organization.",
     "Outlook/classic-outlook-for-windows/authentication/outlook-shows-disconnected-after-enabling-modern-authentication.md",
     "modern_authentication"),

    # --- cluster: bitlocker_tpm (23 sibling articles in the KB, 5 sampled here) ---
    ("BitLocker won't turn on and the error says the TPM is defending against dictionary "
     "attacks and is in a time-out period.",
     "support/windows-client/windows-security/bitlocker-cannot-encrypt-a-drive-known-tpm-issues.md",
     "bitlocker_tpm"),
    ("BitLocker encryption keeps failing on a drive but it's not a TPM problem -- access is "
     "denied when trying to encrypt a removable drive.",
     "support/windows-client/windows-security/bitlocker-cannot-encrypt-a-drive-known-issues.md",
     "bitlocker_tpm"),
    ("A device that has BitLocker enabled is still showing as Not compliant in Intune.",
     "support/mem/intune/device-protection/bitlocker-encrypted-device-not-compliant.md",
     "bitlocker_tpm"),
    ("Our Azure VM won't boot and shows a BitLocker-related error on startup.",
     "support/azure/virtual-machines/windows/troubleshoot-bitlocker-boot-error.md",
     "bitlocker_tpm"),
    ("After installing a UEFI or TPM firmware update on a Surface device, the user is "
     "suddenly asked for the BitLocker recovery key.",
     "support/devices/prompted-bitlocker-recovery-key-installing-updates-surface-uefi-tpm-firmware-surface-device.md",
     "bitlocker_tpm"),

    # --- cluster: federation_certificate (8 sibling articles, 3 sampled here, one of which
    # is a near-exact-title duplicate of the "distinctive" federation query above -- a good
    # stress test for whether the retriever confuses the two) ---
    ("Running the Hybrid Configuration Wizard says no federation trust is configured for "
     "this organization.",
     "Exchange/ExchangeHybrid/hybrid-configuration-wizard-errors/no-federation-trust-is-configured-for-this-organization-error.md",
     "federation_certificate"),
    ("Users can't sign in to Microsoft 365 after we changed our federation service endpoint.",
     "Microsoft365/admin/admin/active-directory/sign-in-fails-if-federation-endpoint-changes.md",
     "federation_certificate"),
    ("One of our on-premises federation service certificates is about to expire -- will "
     "that break sign-in?",
     "Microsoft365/admin/admin/authentication/federation-service-certificate-expire.md",
     "federation_certificate"),

    # --- cluster: mfa (10 sibling articles across mfa/multi-factor, 3 sampled here) ---
    ("A user can't set up MFA because they already have five devices registered with the "
     "authenticator app.",
     "support/entra/entra-id/mfa/cant-set-up-mfa-five-devices-registered.md",
     "mfa"),
    ("A user lost their phone and now can't sign in because Multi-Factor Authentication is "
     "asking for a code from that device.",
     "support/entra/entra-id/mfa/cannot-use-mfa-signin-lose-phone.md",
     "mfa"),
    ("Some users who are enrolled in Multi-Factor Authentication are never being prompted "
     "for a second verification step.",
     "support/entra/entra-id/mfa/multi-factor-auth-second-verification.md",
     "mfa"),

    # --- cluster: exchange_cannot_connect ("can't connect" / "cannot connect" articles,
    # dozens in the KB, 3 sampled here, deliberately excluding the ones already covered
    # by the modern_authentication cluster) ---
    ("We can't connect to the Security and Compliance PowerShell module for our tenant.",
     "Exchange/ExchangeOnline/administration/cannot-connect-to-security-compliance-powershell.md",
     "exchange_cannot_connect"),
    ("Federated users in our organization can't connect to their Exchange Online mailbox at all.",
     "Exchange/ExchangeOnline/administration/federated-users-cannot-connect-to-exchange-online-mailbox.md",
     "exchange_cannot_connect"),
    ("Outlook can't connect when our network routes traffic through a proxy configured "
     "via a PAC file.",
     "Exchange/ExchangeOnline/administration/outlook-cannot-connect-via-proxy-set-by-pac.md",
     "exchange_cannot_connect"),

    # --- cluster: hcw_error_codes (14 sibling "Hybrid Configuration Wizard fails with
    # error <code>" articles -- extremely close lexically, a strong BM25 stress test since
    # only the exact code number distinguishes them) ---
    ("Hybrid Configuration Wizard fails with HCW8008, says the server doesn't have the "
     "Client Access server role installed.",
     "Exchange/ExchangeHybrid/hybrid-configuration-wizard-errors/hcw8008-not-have-client-access-server-role-installed.md",
     "hcw_error_codes"),
    ("Running Hybrid Configuration Wizard gives an HCW8034 or HCW8057 error.",
     "Exchange/ExchangeHybrid/hybrid-configuration-wizard-errors/hcw8034-or-hcw8057-error-when-runninghybrid-configuration-wizard.md",
     "hcw_error_codes"),
    ("Hybrid Configuration Wizard fails with HCW8039, an address space error.",
     "Exchange/ExchangeHybrid/hybrid-configuration-wizard-errors/hcw8039-address-space-error.md",
     "hcw_error_codes"),
    ("We get a 429 error when running the Hybrid Configuration Wizard.",
     "Exchange/ExchangeHybrid/hybrid-configuration-wizard-errors/error-429-in-hcw.md",
     "hcw_error_codes"),

    # --- cluster: teams_meeting (9 sibling articles, 4 sampled here) ---
    ("External attendees dialing into a Teams meeting through PSTN or a video room device "
     "can't join.",
     "Teams/meetings/cannot-join-cvi-pstn-meeting.md",
     "teams_meeting"),
    ("People from outside our organization are blocked from joining our Teams meeting.",
     "Teams/meetings/external-participants-join-meeting-blocked.md",
     "teams_meeting"),
    ("Users are having problems with the chat during a Teams meeting.",
     "Teams/meetings/meeting-chat-issues.md",
     "teams_meeting"),
    ("The organizer of a scheduled Teams meeting is unable to start it.",
     "Teams/teams-conferencing/organizer-cant-start-teams-meeting.md",
     "teams_meeting"),
]


def hit_at_k(results: list[dict], expected_rel_path: str) -> bool:
    return any(r["source_path"] == expected_rel_path for r in results)


def evaluate(rank_fn, chunk_lookup: dict, parent_index: dict) -> dict:
    """rank_fn(query) -> ranked (chunk_id, score) list, already pooled.
    Returns recall broken down overall, by mode (raw/expanded), and by query group."""
    modes = ("raw", "expanded")
    hits = {(mode, k): 0 for mode in modes for k in K_VALUES}
    hits_by_group = defaultdict(lambda: {(mode, k): 0 for mode in modes for k in K_VALUES})
    counts_by_group = defaultdict(int)
    misses = {(mode, k): [] for mode in modes for k in K_VALUES}

    for query, expected, group in QUERIES:
        counts_by_group[group] += 1
        ranked = rank_fn(query)
        for k in K_VALUES:
            raw_results = retrieve._collect_results(ranked, k, chunk_lookup, None)
            expanded_results = retrieve._collect_results(ranked, k, chunk_lookup, parent_index)
            for mode, results in (("raw", raw_results), ("expanded", expanded_results)):
                if hit_at_k(results, expected):
                    hits[(mode, k)] += 1
                    hits_by_group[group][(mode, k)] += 1
                else:
                    misses[(mode, k)].append((query, expected, group))

    total = len(QUERIES)
    return {
        "total": total,
        "recall": {key: count / total for key, count in hits.items()},
        "recall_by_group": {
            group: {key: count / counts_by_group[group] for key, count in group_hits.items()}
            for group, group_hits in hits_by_group.items()
        },
        "counts_by_group": dict(counts_by_group),
        "misses": misses,
    }


def print_report(name: str, report: dict) -> None:
    k = K_VALUES[-1]  # the headline K used for the group breakdown and miss list

    print(f"\n=== {name} (n={report['total']}) ===")
    print(f"{'mode':10s} " + " ".join(f"Recall@{kv:<3d}" for kv in K_VALUES))
    for mode in ("raw", "expanded"):
        row = " ".join(f"{report['recall'][(mode, kv)]:.2f}     " for kv in K_VALUES)
        print(f"{mode:10s} {row}")

    print(f"\nBy group, Recall@{k} (expanded):")
    distinctive_n = report["counts_by_group"].get("distinctive", 0)
    if distinctive_n:
        print(f"  {'distinctive':24s} n={distinctive_n:<3d} "
              f"{report['recall_by_group']['distinctive'][('expanded', k)]:.2f}")
    cluster_groups = sorted(g for g in report["counts_by_group"] if g != "distinctive")
    for group in cluster_groups:
        n = report["counts_by_group"][group]
        print(f"  {group:24s} n={n:<3d} {report['recall_by_group'][group][('expanded', k)]:.2f}")

    still_missing = report["misses"][("expanded", k)]
    if still_missing:
        print(f"\nStill missed at Recall@{k} (expanded):")
        for query, expected, group in still_missing:
            print(f"  - [{group}] {expected}")
            shown = query[:90] + "..." if len(query) > 90 else query
            print(f"    query: \"{shown}\"")


def main() -> None:
    config = retrieve.get_config()
    bm25_path = PROJECT_ROOT / config["BM25_PATH"]
    vector_db_path = PROJECT_ROOT / config["VECTOR_DB_PATH"]

    print(f"Evaluating on {len(QUERIES)} queries, K={K_VALUES}, pool={POOL}")
    print("Loading chunk lookup + parent index ...")
    chunk_lookup = retrieve.load_chunk_lookup(retrieve.CHUNKS_PATH)
    parent_index = retrieve.build_parent_index(chunk_lookup)

    print("Loading BM25 index ...")
    bm25_index = retrieve.load_bm25_index(bm25_path)
    bm25_report = evaluate(
        lambda q: retrieve.bm25_rank(q, bm25_index, pool=POOL),
        chunk_lookup, parent_index,
    )

    print(f"Loading embedding model: {config['EMBEDDING_MODEL']} ...")
    model = SentenceTransformer(config["EMBEDDING_MODEL"])
    collection = retrieve.get_chroma_collection(vector_db_path, config["EMBEDDING_MODEL"])
    vector_report = evaluate(
        lambda q: retrieve.vector_rank(q, model, config["EMBEDDING_MODEL"], collection, pool=POOL),
        chunk_lookup, parent_index,
    )

    print(f"Loading reranker model: {config['RERANKER_MODEL']} ...")
    cross_encoder = retrieve.load_cross_encoder(config["RERANKER_MODEL"])
    hybrid_report = evaluate(
        lambda q: retrieve.hybrid_rank(q, bm25_index, model, config["EMBEDDING_MODEL"], collection,
                                        chunk_lookup, cross_encoder, pool=POOL),
        chunk_lookup, parent_index,
    )

    print_report("BM25", bm25_report)
    print_report("Vector", vector_report)
    print_report("Hybrid (fusion + metadata boost + rerank)", hybrid_report)


if __name__ == "__main__":
    main()
