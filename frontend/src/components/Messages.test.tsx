import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Message } from "../api";
import { FixCard, MessageView, QuestionCard } from "./Messages";

const fix: Message = {
  id: 2, role: "agent", kind: "fix", content: "plain text version", created_at: "2026-10-08T10:00:00Z",
  payload: {
    diagnosis: "The Docker daemon is not running.", verification: "Run docker ps again.",
    steps: [{ text: "Start the daemon and retry.", evidence_ids: ["E1"] }, { text: "Set DOCKER_HOST for SDKs.", evidence_ids: ["E2"] }],
    sources: [
      { id: "E1", title: "Unable to connect to the Docker daemon", url: "https://github.com/docker/docs/x.md", tier: "kb", official: true },
      { id: "E2", title: "docker.sock question", url: "https://stackoverflow.com/q/1", tier: "tickets", official: false, license: "CC BY-SA 4.0" },
      { id: "E3", title: "Post-Installation Steps", url: "https://github.com/bobbyiliev/x.md", tier: "kb", official: false, source_tier: "supplementary", license: "MIT" },
    ],
  },
};
const question: Message = {
  id: 1, role: "agent", kind: "question", created_at: "2026-10-08T10:00:00Z",
  content: "Which of these sounds closest to your problem?\n  1. Unable to connect to the Docker daemon\n  2. Certificates not set up correctly\n(reply with the number, or tell me if none of these fit)",
  payload: { options: ["Unable to connect to the Docker daemon", "Certificates not set up correctly"], feature: "issue" },
};

describe("FixCard", () => {
  it("shows the diagnosis, cited steps, and labels official versus community sources", () => {
    render(<FixCard message={fix} active={false} busy={false} onAction={() => {}} />);
    expect(screen.getByText("The Docker daemon is not running.")).toBeInTheDocument();
    expect(screen.getByText(/Start the daemon and retry\./)).toBeInTheDocument();
    expect(screen.getByText("Official docs")).toBeInTheDocument();
    expect(screen.getByText("Community answer")).toBeInTheDocument();
    expect(screen.getByText("Community guide")).toBeInTheDocument();                // third-party tutorials are not "Official docs"
    expect(screen.getByText("MIT")).toBeInTheDocument();
    expect(screen.getByText("CC BY-SA 4.0")).toBeInTheDocument();                 // community answers carry their licence
    expect(screen.getByRole("link", { name: "Unable to connect to the Docker daemon" })).toHaveAttribute("href", "https://github.com/docker/docs/x.md");
    expect(screen.queryByText("That fixed it")).not.toBeInTheDocument();           // buttons only on the live, latest fix
  });
  it("offers the two outcome buttons when active and reports the choice", async () => {
    const onAction = vi.fn();
    render(<FixCard message={fix} active busy={false} onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: "Still not working" }));
    await userEvent.click(screen.getByRole("button", { name: "That fixed it" }));
    expect(onAction.mock.calls).toEqual([["not_fixed"], ["resolved"]]);
  });
  it("disables the buttons while a request is in flight", () => {
    render(<FixCard message={fix} active busy onAction={() => {}} />);
    expect(screen.getByRole("button", { name: "That fixed it" })).toBeDisabled();
  });
});

describe("QuestionCard", () => {
  it("renders the menu as buttons and sends the chosen option text", async () => {
    const onChoose = vi.fn();
    render(<QuestionCard message={question} active busy={false} onChoose={onChoose} />);
    expect(screen.getByText("Which of these sounds closest to your problem?")).toBeInTheDocument();
    expect(screen.queryByText(/reply with the number/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Certificates not set up correctly" }));
    await userEvent.click(screen.getByRole("button", { name: "None of these fit" }));
    expect(onChoose.mock.calls).toEqual([["Certificates not set up correctly"], ["None of these fit."]]);
  });
  it("offers just yes / no / not sure for a question about one cause, with no 'none of these fit'", async () => {
    const onChoose = vi.fn();
    const q: Message = { id: 5, role: "agent", kind: "question", created_at: "", content: "Does this happen when anti-virus software is installed?\n(yes, no, or not sure)",
                         payload: { options: ["Yes", "No", "Not sure"], feature: "trait:desktop::fails when anti-virus" } };
    render(<QuestionCard message={q} active busy={false} onChoose={onChoose} />);
    expect(screen.queryByRole("button", { name: "None of these fit" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "No" }));
    expect(onChoose.mock.calls).toEqual([["No"]]);
  });
  it("lists symptoms to tick, sends the ticked wording together, and offers 'none of these'", async () => {
    const onChoose = vi.fn();
    const symptoms = ["Docker Desktop never opens after I start it", "Pulls stop with a 429 error", "Nobody on the team can sign in"];
    const q: Message = { id: 6, role: "agent", kind: "question", created_at: "", content: "A few different things could be behind this. Which of these are you seeing? You can pick more than one.\n  1. a\n  2. b",
                         payload: { options: [...symptoms, "None of these, let me describe it"], feature: "pick:a||b||c" } };
    render(<QuestionCard message={q} active busy={false} onChoose={onChoose} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();                       // nothing ticked yet
    await userEvent.click(screen.getByLabelText("Pulls stop with a 429 error"));
    await userEvent.click(screen.getByLabelText("Nobody on the team can sign in"));
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await userEvent.click(screen.getByRole("button", { name: "None of these, let me describe it" }));
    expect(onChoose.mock.calls).toEqual([["Pulls stop with a 429 error; Nobody on the team can sign in"], ["None of these, let me describe it."]]);
    expect(screen.queryByRole("button", { name: "None of these fit" })).not.toBeInTheDocument();
  });
  it("shows no buttons once answered", () => {
    render(<QuestionCard message={question} active={false} busy={false} onChoose={() => {}} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("MessageView", () => {
  const noop = () => {};
  it("labels engineer replies and renders customer text", () => {
    const { rerender } = render(<MessageView message={{ id: 3, role: "engineer", kind: "engineer_reply", content: "Looking now.", payload: {}, created_at: "", author: "enid" }} isLast active={false} busy={false} onChoose={noop} onAction={noop} />);
    expect(screen.getByText(/Support engineer · enid/)).toBeInTheDocument();
    rerender(<MessageView message={{ id: 4, role: "customer", kind: "text", content: "my container dies", payload: {}, created_at: "" }} isLast active busy={false} onChoose={noop} onAction={noop} />);
    expect(screen.getByText("my container dies")).toBeInTheDocument();
  });
});
