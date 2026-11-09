# Compliance notes (read before using AI agents)

_Not legal advice. Terms change; the linked pages are the authority. Last checked October 2026._

Mitra Home is a local tool. It does not include, resell or host any AI service. Each family installs the AI tool they choose
and signs in with their **own** account or API key. These are the rules the design follows, and what you must do.

## Anthropic / Claude
Sources: [Claude Code legal & compliance](https://code.claude.com/docs/en/legal-and-compliance),
[Consumer Terms](https://www.anthropic.com/legal/consumer-terms), [Usage Policy](https://www.anthropic.com/legal/aup).

| Rule (summarised) | What Mitra Home does | What you must do |
|---|---|---|
| Subscription (Free/Pro/Max) sign-in is for Claude Code and Anthropic's own apps. Other products and tools must use API keys, and may not route requests through someone's subscription login or collect, store or pass on Claude login tokens. | The scheduled jobs and agents run the **unmodified `claude` CLI** that you installed and signed in to yourself. The code never reads, copies or forwards Claude login tokens. The Anthropic provider in `data/llm.py` accepts **API keys only** and refuses subscription tokens. | Install Claude Code from Anthropic. Sign in yourself. Never paste a Claude login token into Mitra Home or any other tool. Do not use Mitra Home through third-party "harnesses" that borrow your subscription (OpenClaw-style tools). |
| One account per person: you may not share your login or make your account available to anyone else. Users must be 18+. | One family = one folder = one PC = that family's own account. The kid views of the dashboard contain **no AI**. | Do not let relatives, friends or the maintainer use your Claude login. Children do not use Claude through this tool. If you help another family, they sign in with their own account on their own PC. |
| Scripted/automated access to a subscription is only allowed where Anthropic permits it. Pro/Max limits assume ordinary, individual use. | Scheduled jobs use Claude Code's documented non-interactive mode (`claude -p`) with least-privilege tools, at a low cadence (the 2-hourly inbox check is **off by default** and only calls Claude when files are waiting). A daily cap (`ai.max_runs_per_day`, default 12) stops runaway use. | For heavy or unattended use, use an **API key** (billed to you) instead of a subscription. Expect usage limits to apply. |
| Consumer accounts may be used to improve models unless you opt out in your account settings. | Nothing is sent without an agent reading a file or email you asked it to. | Before processing statements, medical or tax documents, review your Claude privacy / "help improve Claude" setting and opt out if you prefer. |
| Usage Policy: for legal, medical, insurance and financial matters a qualified professional must review advice before decisions; disclose AI use; do not misuse health or other private data. | Everything is "records and checklists, not advice". Agents are instructed to say so and to state that answers are AI-assisted. | Confirm tax, insurance, legal and medical decisions with a licensed professional. Use only your own household's data. |
| Health-care (HIPAA) coverage needs an Anthropic agreement; consumer accounts are not covered. | Only minimal health data; a diagnosis only if an adult types it into the PC-only Critical info card, which no AI, phone or chat ever reads. | Do not process other people's medical records. |

## Other AI providers (optional, `data/llm.py`)
- **OpenAI, Google Gemini:** use your own **API key** (environment variable or `config/secrets.env`). Do not use consumer chat subscriptions or their login tokens. Check each provider's data-retention and training terms for API traffic.
- **OpenRouter:** one API key that reaches many models. Every request asks OpenRouter to route only to hosts that do not store or train on prompts (`provider.data_collection: deny`); the model host's own terms still apply, so pick a model from a provider you trust.
- **Ollama / local models:** nothing leaves your PC. Accuracy on statements is lower.
- **Traditions (optional, `data/traditions.py`):** a family's religion or culture is sensitive. The traditions you list stay in
  `config/family.json` on this PC and are never synced, copied to Drive or sent to a chat bot. Only when you switch on the yearly
  look-up does your provider receive the tradition's name, the year and the country code, once a year per tradition, with
  nothing else from your records. Leave the list empty, or the look-up off, and nothing about it leaves the PC.
- Mitra Home never sends data to any provider unless you selected one in `config/family.json` (`ai.provider`) and accepted the consent text in the wizard. The default is `claude_code` for agents and `none` for the Python pipelines.

## Other tools (Cursor, Codex, Gemini CLI, ...)
`AGENTS.md` / `GEMINI.md` only tell such a tool how to behave in this folder when the person uses it **interactively, under their own
account**; its terms apply.

### Signed-in CLIs as a text model (`claude_cli`, `codex_cli`, `gemini_cli`, since v0.6.0)
Mitra Home can start the vendor's **own, unmodified CLI** that you installed and signed in to, give it text and read text back. It does
not read, copy, store or forward the CLI's login files or tokens, does not modify the CLI, and removes Mitra Home API keys from the
child's environment. Each CLI starts in an empty temp folder. `claude` runs with every tool and MCP server off, so it sees only the
text it is given. `codex` runs in its read-only sandbox, which stops writes but **not reads**: the model can still read files
anywhere on this PC (filed originals included, unmasked), and a document written to steer it could make it do so. That is why
Settings offers only `claude`; `codex` and `gemini` are terminal-only (`python onboard.py`), at your own choice.
| CLI | Notes (checked October 2026; the vendor's current terms are the authority) |
|---|---|
| `claude` | Anthropic: signing in to the unmodified Claude Code with your own subscription is allowed; Pro/Max limits assume ordinary individual use. |
| `codex` | OpenAI documents `codex exec` for scripts and recommends an API key for automation; a ChatGPT sign-in works but its token file is sensitive. Its read-only sandbox can still read any file (audit, 28 October 2026), so masking is not guaranteed; not offered in Settings until its shell can be switched off. Read OpenAI's terms for your plan. |
| `gemini` | Google: the CLI's terms say accessing the underlying service with third-party software is a violation, and on the **free tier prompts and outputs may be used to improve Google products**. Do not use the free tier for family documents; prefer a paid Gemini API key. |
Unattended (scheduled) runs through these sign-ins are **off by default** (`ai.allow_unattended_cli`). You run `python data/ai_intake.py`
or `python data/assistant.py` yourself, or use an API key / Ollama for unattended use. The provider-neutral assistant (`data/assistant.py`) sends your typed request, the last few turns of the same conversation
(so a follow-up such as "and Sam's too?" works; kept only in the open dashboard tab or, for the phone bot, in memory for 30
minutes, never on disk), and for questions the results of its look-ups, at most four rounds per request (SSN, account and
card numbers, emails, phones, dates of birth and addresses masked; see `python data/llm.py redact-preview`), to the provider you chose with your own API key. Free-tier Gemini is refused unless you confirm a paid tier.

## Maintainer / sharing rules
- Do **not** run other families' documents through your own subscription or keys, and do not host this for others. That is account sharing / reselling.
- Do not bundle or modify Claude Code, and do not collect families' credentials. Families install it from Anthropic.
- Mitra Home is not affiliated with or endorsed by Anthropic, OpenAI or Google. Product names belong to their owners.
- The GitHub token used for updates (`MITRAHOME_TOKEN`) is read-only access to this repository only. It is unrelated to any AI account.

## Google Drive (phone drop box and briefs)
Mitra Home uses the **Google Drive for Desktop** app you install and sign in to yourself; it reads and writes ordinary files in that folder and never calls a Google API or sees Google credentials. Files you drop in Drive `Inbox` are treated as untrusted data (type, size and name checks, then the same AI rules as any document). Briefs placed in Drive `Brief` contain vendor names and amounts, so they are visible to Google and to anyone you share that folder with.

## Google (Gmail, Calendar)
Mail and calendar access goes through the **claude.ai connectors** you authorise yourself, not through code in this repository. Mitra Home deliberately ships no direct Google API integration (it would require Google OAuth app verification for sensitive scopes). Use a dedicated agent mailbox as the wizard suggests, and never forward mail you are not entitled to share.

## Mail folder (IMAP)
Settings > Connections > Mail folder reads one folder of a mailbox over IMAP with TLS, read-only (messages stay unread; nothing is moved or deleted). Use a mailbox made only for Mitra Home and forward to it what it should file, and sign in with an **app password** the mail provider issues for one app, never the account's own password. The app password is typed only on the family's PC, kept in `config/secrets.env` (never backed up, never shown again, never sent to an AI) and can be revoked at the provider at any time. Attachments and message text then follow the same rules as any document dropped in the inbox.

## Data you should not put in
Other people's confidential data, account passwords or PINs, full card/bank/SSN numbers (the tool stores last four only), diagnoses, or anything you could not lawfully share with your chosen AI provider.
