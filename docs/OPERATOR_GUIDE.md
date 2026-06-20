# Operator guide for a non-coder product manager

## Your responsibility

Explain:

- who the product is for;
- what the user should be able to accomplish;
- what a successful result looks like;
- what must not break;
- unacceptable privacy, cost, security, or data outcomes;
- ideas that may belong later.

You do not need to name functions, packages, databases, or design patterns.

## A useful product brief

Bad:

> Build a modern dashboard.

Better:

> Build a client portal. A client signs in, sees only their own projects, uploads documents, views status history, and messages our team. Existing admin workflows must remain unchanged. A browser demonstration must show one successful client journey and one denied cross-client access attempt.

## Adding ideas while the product is being built

Capture an idea without silently changing active scope:

```bash
umsmfburasbofe idea add "Clients should eventually be able to approve estimates"
```

Pending ideas are attached to the next run and classified during product analysis. They may become:

- a clarification of the current request;
- a required dependency;
- a later feature;
- a global product rule;
- a bug;
- an experiment;
- an architecture decision.

The coding agent cannot decide to add the idea by itself.

## Reading the result

UMSMFBURASBOFE's final report emphasizes:

- product behavior delivered;
- observable acceptance outcomes;
- existing components reused;
- verification commands and results;
- independent review status;
- changed files;
- remaining risk;
- evidence locations.

You approve the product behavior and demonstration. You are not required to interpret the code diff as the primary acceptance method.
