---
paths:
  - "README.md"
  - "REFERENCE.md"
  - "CHANGELOG.md"
  - "CONTRIBUTING.md"
  - "docs/**"
---

> **This is the public-face profile of this repository.** It loads when one of the public
> documents below is opened, and it says who each layer of the documentation is written for and
> in what character, so that an edit is made for its reader and not for its author. It is
> reference, not a task list: nothing here is an instruction to act on right now.

## The layers of the public face

| layer | files or globs | audience | character | language |
|---|---|---|---|---|
| package front door | `README.md` | a developer of a Scry server (scry-mame, scry-dosbox-x) or a contributor to one, who needs to know what the shared package holds before writing a helper twice; and a visitor who arrived from a server's README | reference first: what the package is, which module holds what, how a server uses it, how to try a server by hand, how to develop here. Short; the WHY of a module's contract lives in its docstring, not here. No history and no measurement | English |

## What is public and what is not

- Public: `README.md`.
- Not public and not this profile's business: `.claude/`.
- Extra READMEs kept public: none.

## Generated documents

None here. The reference generator this package holds writes the servers' `REFERENCE.md`, which
are each server's to profile.

## Captures

- None: the package has no surface of its own to show, and the auditor does not report a missing
  capture.

## Limits

- Language: every public document here is in English. This line is the declaration.
- A public document over 64 KB whose headings also belong to more than one layer is a God README.
- The README closes with the credits line, verbatim, its links resolving; it is attribution the
  project ships, not a leak, and a README without it is the finding:

  `Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).`
- Nothing else is exempt: a dated measurement, a note on the project's own history, a
  home-directory path or an assistant's name in a tracked file outside `.claude/` is a finding.
