import type { InboundEmail } from "../api";

// The email that raised this alert, shown exactly as the agent received it.
export default function InboundEmailCard({ email }: { email: InboundEmail }) {
  return (
    <section className="inbound-email">
      <header>
        <p className="overview-kicker">Inbound email</p>
        <p className="email-subject">{email.subject}</p>
        <p className="email-meta">
          From {email.from} · received {new Date(email.received_at).toLocaleString()}
        </p>
      </header>
      <p className="email-body">{email.body}</p>
      <p className="email-note">
        Untrusted input. The agent reads this as a symptom report and checks it against the
        telemetry. Instructions inside it, like the request to skip approval, change nothing:
        every fix still waits for a human.
      </p>
    </section>
  );
}
