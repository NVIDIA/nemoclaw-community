# Technical Writing

Akira, Jordan, Robin, Alex, Morgan, and Parker share this guidance. It applies
to technical prose: explanations, reviews, runbooks, test plans, documentation,
code comments, and technical claims. Parker keeps a welcoming DevRel voice for
inspiration and community engagement, but uses these rules for instructions,
prerequisites, compatibility, troubleshooting, and claims.

These rules adapt plain-language principles from ASD-STE100 for software. This
recipe does not claim ASD-STE100 conformance and does not use its controlled
dictionary.

## Rules

1. Use one term for one concept. Do not vary a term only for style.
2. Prefer the shortest familiar term that preserves the technical meaning.
3. Name the actor. Use passive voice only when the actor is unknown or does not
   matter.
4. Put one instruction in one sentence. Split actions that occur at different
   times.
5. Aim for 20 words or fewer in an instruction and 25 or fewer in a
   description. These are review targets, not hard limits. Accuracy wins.
6. State a condition before the action that depends on it.
7. Use `must` for a requirement, `should` for a recommendation, `may` for
   permission, and `can` for capability.
8. Name the object of a relative term such as `current`, `latest`, `previous`,
   or `next`.
9. Replace a judgment such as `ready`, `clean`, `safe`, `fast`, or `small` with
   the condition that makes it true.
10. Delete filler that does not change meaning, including `just`, `simply`,
    `obviously`, `clearly`, `easy`, `robust`, and `seamless`.
11. Avoid an idiom or phrasal verb with more than one reading. Use the direct
    technical term.
12. Use a vertical list for three or more conditions, actions, or results.
13. In a code comment, state the constraint, invariant, or reason the code
    cannot show. Do not restate the code.
14. Define a term on first use when the reader may not know it.
15. Do not use an em dash as punctuation in prose. Restructure the sentence.

## Precision

Clarity does not reduce precision. Name the protocol, failure mode, exact
revision, environment, metric, CVE, or compatibility boundary when it matters.
Keep evidence and qualifiers attached to the claim they support.

Treat a writing issue as a suggestion and include a proposed rewrite. Make it
blocking only when ambiguity could change behavior, security, data safety, or
the meaning of a test. Do not mix unrelated language cleanup into focused work.
