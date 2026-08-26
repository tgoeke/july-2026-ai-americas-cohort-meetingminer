You are helping me turn meeting notes and transcripts into architecture-ready analysis.



Inputs may include:

\- Meeting summary

\- Action items

\- Teams notes

\- Transcript excerpts

\- Raw transcript

\- My comments or corrections



Please process the material in phases:



1. Rebuild the meeting summary

  \- Identify what actually happened

  \- Separate decisions, discussions, open questions, and unresolved issues

  \- Avoid over-interpreting unclear transcript sections



2. Extract key points

  \- Current-state process

  \- Future-state direction

  \- System ownership

  \- Data ownership

  \- Integration dependencies

  \- Controls / compliance implications

  \- Edge cases and exceptions



3. Extract action items

  \- Owner

  \- Action

  \- Dependency

  \- Due date if stated

  \- Open decision supported by the action



4. Extract assumptions

  \- Explicit assumptions stated in the meeting

  \- Implied assumptions required by the design

  \- Weak or unvalidated assumptions



5. Extract concerns / risks

  \- Process risks

  \- Data risks

  \- Integration risks

  \- Compliance risks

  \- Operational risks

  \- Edge-case risks



6. Identify integrations

  \- Source system

  \- Target system

  \- Direction

  \- Trigger

  \- Frequency if discussed

  \- Data payload

  \- Dependency / sequencing requirements



7. Identify canonical data model candidates

  \- Core entities

  \- Relationship entities

  \- Composite keys

  \- Source of truth

  \- Mutable vs immutable fields

  \- Lifecycle rules



8. Extract master data that must be pushed or synchronized

  \- Entity

  \- Source system

  \- Target system

  \- Required attributes

  \- Purpose



9. Extract business rules

  \- Write them as enforceable rules

  \- Distinguish confirmed rules from assumptions

  \- Flag rules that need validation



10. Build process models

  \- Business process flow

  \- Value stream map

  \- System-level sequence diagram

  \- Role-based swimlane diagram



Output style:

\- Be concise but complete

\- Use structured headings

\- Use tables where useful

\- Mark items as Confirmed / Assumed / Open / Risk

\- Preserve uncertainty

\- Do not invent missing facts

\- Call out contradictions between notes and transcript



After processing, end with:

\- Decisions made

\- Open decisions

\- Highest-risk assumptions

\- Recommended next clarification questions



Focus the analysis for an enterprise architecture audience. Emphasize system boundaries, integration contracts, canonical data, source-of-truth decisions, process dependencies, and control points.