/**
 * The Threads route's placeholder (story 10.5).
 *
 * Threads is the second primary view, so the shell's nav links to it from
 * every screen and the route must resolve to something rather than falling
 * through to the unknown-path catch-all. The screen itself — bands →
 * meetings → moments with continuous zoom — is story 10.6, built in parallel;
 * it replaces this component and keeps the route file.
 *
 * It states its own absence in one sentence rather than showing an empty
 * canvas or an invented band, which is the same rule every other absent thing
 * in this product follows.
 */
export function ThreadsPlaceholder() {
  return (
    <section className="flex flex-col gap-2" data-testid="threads-placeholder" aria-label="Threads">
      <h2 className="text-sm font-medium text-muted-foreground">Threads</h2>
      <p className="text-sm">
        No Threads timeline on this build yet — the zoomable timeline mounts here.
      </p>
    </section>
  )
}
