---
tags:
  - {{product_tag}}
spec_role: code-report
spec_doc_type: code-report
wiki_pinned_topics:
  - wiki/doc-kind/code-report
  - wiki/product/{{product}}
  - wiki/category/{{category}}
---
# {{slug}} — code-report
<!-- The working journal of a release's builds, one `#### build <k>` entry per build: what landed, what stayed open, and the log of every step, written for the operator during execution and never after the fact. A new build's entry goes first, right under this title, the entries of earlier builds stay below it unchanged, and a continuation of the same build rewrites that build's entry whole in place. What was planned lives in the sibling plan, and no plugin path, plugin version or environment variable belongs anywhere in this journal. -->

## Result
<!-- What landed and the evidence it works, each goal shown by what the product does: a behaviour test that ran, or the command itself, never the existence of a test of a given name. A few sentences, then each check in plain words — what it checked and how it ended —, never a bare tool name, an internal step name or raw command output in place of a result. What was tried and failed lives in Unresolved problems. -->

## Open questions
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The questions raised against the plan that only the operator can answer and that are still unanswered. One bullet per question, naming the task it blocks. A question already answered lives in Log. -->

## Unresolved problems
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The problems that surfaced during execution and were not solved, limited to work the current plan owed the build. One task line per problem a later run can fix, tagged `#review/send-back` so the operator can tick it, saying what breaks and what was tried; a step left to a person is a plain bullet without a box. A step the current plan no longer contains is not mentioned, and a decision taken to get past a problem lives in Decisions taken alone. -->

## Decisions taken alone
<!-- Optional. When the document has nothing to say here, the section is removed together with its heading. The decisions made without the operator because the work could not proceed otherwise. One bullet per decision: what was chosen, and on what grounds. A question left for the operator lives in Open questions. -->

## Log
<!-- The steps of the build and what each verification returned. One entry per step, in the order the steps ran, each check stated in plain words as in Result. The final outcome lives in Result. -->
