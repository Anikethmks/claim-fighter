/** Plain-language privacy notice. Have it reviewed against the DPDP Act before a wide launch. */
export default function Privacy() {
  return (
    <section className="card prose">
      <h1>Privacy and your documents</h1>
      <p className="muted">Last updated: 5 November 2026</p>

      <h3>What we collect</h3>
      <ul>
        <li>Your email address, to sign you in.</li>
        <li>The documents you upload (insurer letter, policy, hospital bill), which contain health and financial information.</li>
        <li>Anything you type: notes, answers, chat messages, and the result you report.</li>
      </ul>

      <h3>Why we use it</h3>
      <p>Only to analyse your claim, draft your complaint and track your deadlines. We don't sell your data or use it for advertising.</p>

      <h3>Who processes it</h3>
      <p>
        To read and analyse your documents, their contents are sent to our AI provider (OpenAI) over an encrypted
        connection. They process it to give us the analysis. We have switched off optional tracing of conversations.
      </p>

      <h3>How long we keep it</h3>
      <ul>
        <li>Uploaded documents are deleted automatically after 30 days.</li>
        <li>You can delete a case at any time from its page. This removes the documents, analysis, letters and chat.</li>
        <li>Anonymous counts (for example, number of cases) may be kept to improve the service.</li>
      </ul>

      <h3>Your consent</h3>
      <p>
        Before analysing a case we ask you to agree to this processing. You can withdraw by deleting your cases.
        Only upload documents about yourself, or about someone who has allowed you to act for them.
      </p>

      <h3>Not legal advice</h3>
      <p>ClaimFighter gives information and drafting help. It is not a law firm and doesn't guarantee any outcome.</p>

      <h3>Contact</h3>
      <p>For questions or deletion requests, reply to any sign-in email.</p>
      <a className="btn btn-secondary" href="#/">Back</a>
    </section>
  );
}
