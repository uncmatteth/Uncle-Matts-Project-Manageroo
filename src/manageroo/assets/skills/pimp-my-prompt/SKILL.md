---
name: "pimp-my-prompt"
description: "Use when a rough, frustrated, ambiguous, overloaded, or reusable request needs to be turned into exact scope, acceptance criteria, fallback rules, or a better agent/system prompt without losing the user's intent. Also use when the user invokes $pimp-my-prompt, asks how to say something, or needs a live task translated into executable instructions."
triggers:
  - "pimp my prompt"
  - "recover intent"
  - "rough request intake"
---

# Pimp My Prompt

Use this skill when the user wants help improving a prompt, prompt template, system instruction, evaluator rubric, or agent workflow prompt.

The goal is not to make the prompt sound smart. The goal is to make it work better.

Many users do not arrive with a clean prompt. They arrive with intent, fragments, hesitations, or rough language.
Your job is to recover the actual job they are trying to get done, not just polish the words they happened to type.

## Designed for rough-draft users
This skill is especially for users who know what they want at a high level but do not naturally phrase requests in a clean, structured way.

Treat rough wording as normal input, not as a failure by the user.
Assume the user may have strong product sense, task sense, or outcome sense even when the phrasing is messy.

Your job is to translate from:
- intent into instruction
- rough language into a clear request
- "I know what I mean" into "the model can reliably act on this"

Do not reward polished wording over real intent.
Do not confuse typos, repetition, or half-formed phrasing with lack of clarity of purpose.

## Core principles
- Optimize for task success, not prompt aesthetics.
- Prefer clarity over cleverness.
- Reduce ambiguity before adding style.
- Keep responsibilities narrow when possible.
- Distinguish between prompt help and task help before rewriting anything.
- Prefer rewrite-and-run over rewrite-only when the user wants help with a live task.
- Decide explicitly how the model should behave when inputs are missing, ambiguous, or out of scope.
- Use examples when examples teach the behavior more reliably than abstract instructions.
- Shorter is better only if it does not remove essential control.

## First classify the prompt
Before rewriting, identify which kind of prompt you are looking at:
- one-off user prompt
- reusable task template
- system or behavior prompt
- extraction or transformation prompt
- agent workflow prompt
- evaluator or judge prompt

Adapt the rewrite strategy to the prompt type. Do not apply the same structure blindly to every case.

## First classify the user's intent
Before rewriting, decide what the user is actually asking for. This is separate from prompt type.

Choose one:
- prompt-formulation help: the user does not know how to ask for something yet and wants help phrasing it
- task execution: the user is using rough wording to ask for the underlying task to be done
- dual mode: the user wants both a better prompt and the task performed

Use these cues:
- If the user talks about wording, phrasing, asking better, or not knowing how to say it, lean toward prompt-formulation help.
- If the user is trying to accomplish something concrete now, lean toward task execution.
- If the user explicitly wants to see the better prompt and then wants it used, choose dual mode.

If the wording is rough but the intent is still recoverable, do not force the user to become a better prompt writer before helping them.
Infer the likely job, state one minimal assumption if needed, and proceed.

## What to diagnose
Check the current prompt for:
- unclear or mixed objective
- too many responsibilities in one prompt
- missing input assumptions
- no rule for what to do when information is incomplete
- conflicting instructions or unclear priority order
- vague quality bars such as "good," "better," or "professional"
- loose output formatting that invites drift
- unnecessary verbosity, redundancy, or decorative phrasing
- hidden dependency on domain knowledge, retrieval, or prior conversation state
- instructions that encourage hallucination by leaving too much freedom

## Rewrite strategy
When improving a prompt:
1. State the job clearly.
2. Name the inputs the model should use.
3. Define the priority order when instructions conflict.
4. Tell the model what to do if information is missing, ambiguous, or out of scope.
5. Specify the output shape only as tightly as the task requires.
6. Remove anything that does not materially improve behavior.
7. Split into multiple prompts if the task contains multiple distinct jobs.

## Clarify, Infer, or Refuse
Always decide which behavior is appropriate:
- Clarify when a missing detail would materially change the answer and asking is cheap.
- Infer when a bounded assumption is safe and you can state it briefly.
- Refuse or narrow scope when the request is unsafe, impossible, or would require pretending.

If you infer, keep the assumption minimal and visible.

## Default operating mode

Do not assume the user only wants a rewritten prompt.

Do not use prompt rewriting as a reason to avoid the user’s actual task.

The user’s actual request remains the controlling task. A rewritten prompt may clarify or improve wording, but it must not silently replace, narrow, expand, delay, or reinterpret the user’s request.

When the user’s real intent is task execution, default to this flow:

1. Briefly identify the task.
2. Execute the task directly.
3. Only include a rewritten prompt if it is genuinely useful, and label it `Optional improved prompt:`.
4. Do not require the user to approve the rewritten prompt before completing the task unless the user specifically asked for approval first.

When the user’s real intent is prompt-formulation help, default to this flow:

1. Identify the underlying ask.
2. Rewrite the request clearly.
3. Optionally provide a tighter or more robust version.
4. Do not execute the rewritten prompt unless the user explicitly asks for execution.

When the user’s real intent is both prompt improvement and task execution, default to this flow:

1. Briefly identify the task.
2. Show the improved prompt.
3. Immediately perform the task, unless the user explicitly asked to review or approve the prompt before execution.

Only stop after the rewrite if one of these is true:

* the user explicitly asked for rewrite-only help
* the prompt is a reusable system, template, evaluator, or workflow prompt that is not meant to be executed immediately
* required input is missing and cannot be safely inferred
* the user explicitly asked to review or approve the rewritten prompt before execution

If execution is blocked by missing information, ask one focused question or make one minimal visible assumption.

Do not treat “improving the prompt” as permission to ignore, weaken, alter, or evade the user’s literal request.

Do not claim the rewritten prompt is the user’s intent unless the user said so or the intent is directly supported by the user’s words.

Do not ask for approval merely because a prompt was rewritten. Ask for approval only when approval is required by the user’s wording, missing information, safety, or a genuine ambiguity that cannot be reasonably resolved.

Do not just hand back a better prompt when the user is clearly trying to get work done.

Do not jump into execution when the user is clearly asking only for help formulating the request itself.

## Execution handoff

When applying an improved prompt, do not pretend to quote or reveal an internal hidden process.

Use the improved prompt only as a visible aid for clarity. The user’s actual request remains authoritative.

Keep the handoff compact when applicable:

* `Diagnosis:` one or two sentences
* `Recovered intent:` one brief line when the original ask was messy or underspecified
* `Optional improved prompt:` the rewritten prompt
* `Result:` the completed answer to the user’s actual task
## Tone for rough-draft users
When the user's phrasing is messy but the intent is understandable:
- do not nitpick the wording
- do not lecture them about prompt writing
- do not make them restate the whole request in cleaner language
- reflect back the recovered intent in simple language
- move forward with one minimal assumption when safe

The experience should feel like a smart collaborator helping the user say what they mean, not a teacher grading the wording.

## Output guidance
Default to a compact response unless the user asks for a deep audit.

For a normal request, provide:
1. The main problem with the current prompt.
2. Why it causes weak or inconsistent results.
3. A rewritten prompt.
4. The recovered intent when the user's wording was not the same as the real ask.
5. The result of using that rewritten prompt when the task is immediately runnable.
6. If useful, a tighter variant or a more robust variant.

For a deeper audit, provide:
1. Short diagnosis.
2. Failure modes.
3. Rewrite recommendations.
4. Improved prompt.
5. Result of applying it if applicable.
6. Optional test cases.

## Rewriting rules
- Prefer plain language over internal acronyms.
- Do not force visible chain-of-thought output unless the user explicitly wants visible reasoning.
- Prefer concrete rules over abstract aspirations.
- Prefer examples over long explanations when behavior is subtle.
- Do not over-constrain formatting if the task needs judgment or creativity.
- Do not preserve bad structure just because the original prompt used it.

## Good outcomes
A strong rewrite usually does at least one of these:
- identifies what the user is trying to accomplish even when they phrase it badly
- turns a vague request into a clear job
- separates multiple jobs into stages
- replaces style-heavy text with operational instructions
- adds a missing fallback rule
- adds a realistic output contract
- makes the assistant actually perform the task when execution is possible
- removes instructions that create token cost without improving quality

## Quick examples
Example: rough phrasing, prompt help only
- User: "i know what i want i just dont know how to ask for it"
- Recovered intent: help formulate the request
- Good response shape: explain the likely ask, provide a clean prompt, optionally give a tighter variant, do not execute unless asked

Example: rough phrasing, task execution
- User: "make this query faster i dont know the right database words but it times out when we search invoices"
- Recovered intent: improve query performance now
- Good response shape: state the likely task, rewrite the request if useful, then investigate and fix

Example: rough phrasing, dual mode
- User: "write the prompt better and then use it on this mess"
- Recovered intent: improve phrasing and execute
- Good response shape: diagnosis, improved prompt, result

## Advanced mode
If the user explicitly asks for deep optimization, also:
- produce a minimal version and a robust version
- suggest whether the task should be split into multiple prompts or agents
- include 3 to 5 concrete test cases that would expose prompt failures
- call out any parts that should live outside the prompt in retrieval, tools, or application logic
