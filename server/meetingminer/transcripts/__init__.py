"""Transcript dialects — the acquisition-side converters.

The *pipeline* reads three lineages and only three
(:mod:`meetingminer.pipeline.transcripts`): Teams text, legacy
``<Name> | MM:SS`` blocks, and a speaker-less VTT that contributes end timings.
Anything else a meeting platform exports is converted **here**, at acquisition,
into one of those — so the pipeline's transcript contract stays exactly as
AD-13 fixed it, and every drop in the corpus holds the same three shapes
whatever produced it.

Nothing in this package is imported by the pipeline. It is a producer-side
package: ``mintdrop`` (and, later, the upload-session door) call it before a
drop exists.
"""

from __future__ import annotations
