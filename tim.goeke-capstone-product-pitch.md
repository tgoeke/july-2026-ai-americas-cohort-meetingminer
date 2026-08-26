**Every AI meeting tool today is a summarizer: it hands you prose you have to trust. I'm building the opposite: an evidence engine.**

As a lead application architect, one of my responsibilities is reviewing recorded software demos and turning them into architecture decisions, requirements, and backlog changes. Today that means scrubbing through video, capturing screenshots, aligning them with transcripts, and feeding fragments into an LLM. It takes hours, and a missed screen fails silently: nothing tells me it's gone until someone re-watches the video.

**MeetingMiner** transforms those recordings into durable engineering knowledge.

It takes a Teams recap URL (or a local recording) and constructs a browsable evidence record. Every distinct application screen is captured, every discussion is aligned to what was on the screen, and every piece of generated knowledge remains linked back to the exact moment in the original recording with one-click replay.

Every processed meeting becomes part of a searchable engineering knowledge base. You can search across meetings or ask questions in natural language, but every answer must cite **who** said it, **when** they said it, and let you replay the original evidence.

**No citation. No answer.**

The interesting engineering challenge isn't building another AI meeting assistant. It's building a dependable system on top of probabilistic AI. The architecture keeps deterministic code responsible for truth, treats AI as a contributor of evidence rather than a source of truth, and validates every change against scripted Teams meetings with known ground truth; the bar for capture recall is 100%.

**AI proposes. Provenance verifies. Humans approve.**