# Contributing to Cline Agent Incidents

## What we want

Sessions where the agent did something unsafe, adversarial, or concerning: ran a command it found in a file, deleted the wrong thing, leaked a credential, claimed tests passed when they did not, worked around a refusal, kept looping. The clearer the moment where it went wrong, the more useful the session.

Successful sessions do not belong here. `/upload-hf` can publish those to your own dataset.

## How to contribute

1. Install the plugin: `cline plugin install https://github.com/cline/upload-hf`.
2. In the session where the incident happened, run `/upload-hf`.
3. The agent redacts the transcript, reads the whole preview, and reports `VERDICT: CLEAN` or `VERDICT: NEEDS_ATTENTION`. Read the verdict.
4. Choose "Report an incident". Answer the questions: what happened, which categories from [TAXONOMY.md](TAXONOMY.md), severity, what you expected, why you are contributing.
5. The plugin opens a pull request here. You will get a link. Nothing is uploaded before you confirm.

Do not hand-build pull requests. The plugin's redaction pipeline and file layout are the point; a PR with different files or a hand-edited transcript will be closed.

## What not to submit

- **Code you do not have the right to publish.** Include the repository snapshot only when the repository is yours or is public under a permissive license. Your employer's code needs your employer's permission, not yours.
- **Other people's personal data.** Customer records, support tickets, user e-mails in fixtures. Redaction catches patterns, not context. If the session is about such data, do not submit it.
- **Provider-restricted outputs.** Some model providers forbid redistribution of their outputs. We record the provider and model so consumers can filter, but that does not make a restricted upload acceptable.
- **Sessions you did not run.** Submit your own sessions only.

## Redaction is your responsibility

The plugin does a deterministic pass, your agent reads the whole redacted preview and reports what it finds, and if TruffleHog is installed it scans as a backstop. When the verdict is `NEEDS_ATTENTION`, add the values it names as extra secrets or deny-list entries and re-run. When it is `CLEAN`, still skim the preview yourself for anything only you would recognise: internal hostnames, client names, business context.

Once merged, the session is public and git history is permanent. The pull request is the last cheap place to catch a problem. Review helps, but it cannot know what is sensitive to you.

## The write-up

The agent asks for five things and generates `SUBMISSION.md` from your answers:

- **What I asked for.** Your task, in a sentence or two.
- **What the agent did.** The incident. Reference message numbers.
- **What I expected.** What a well-behaved agent would have done instead.
- **Why I'm contributing.** Optional. What makes this session worth a researcher's time.
- **Notes for reviewers.** Anything about redaction, licensing, or reproduction.

"I do not know why it did this" is a fine answer. Pick categories from the taxonomy; if none fit, pick the closest and say so in the notes. Mark `adversarial` when you set the situation up deliberately (red-team runs, honeypot files); leave it off when the agent did this on its own.

## Review

An automated check runs on every pull request: file layout, schema, taxonomy labels, a second redaction and secret scan, and snapshot licensing. It posts one comment with the result. A maintainer then reads the write-up, looks at the messages you pointed to, and merges.

We may ask for changes, usually a redaction fix, or close without merging, usually for licensing. Closing is not a judgement of your report. Typical turnaround is a few days.

## License

By opening a pull request you license your transcript, trajectory, and write-up under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) and confirm you have the right to do so. Source code in snapshots and patches keeps its own license.

## Removal

Open a discussion titled `Removal request: <session_hash>`. We remove the session and rebuild the manifest. When the request involves sensitive data we also ask Hugging Face to purge it from history.

## Contact

Questions go in the Discussions tab. Security-sensitive reports about this dataset or the plugin: security@cline.bot.
