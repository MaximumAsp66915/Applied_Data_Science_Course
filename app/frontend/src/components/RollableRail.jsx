import { ChevronRight } from "lucide-react";

// A horizontally-scrollable "rollable" rail with a title/eyebrow header and
// an optional "see all" action. Used for latest tracks, latest artists,
// a user's uploaded tracks, etc. Snap-scrolling gives it a deliberate,
// tactile feel rather than a raw overflow-x div.
export default function RollableRail({ eyebrow, title, onSeeAll, children, empty }) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);

  return (
    <section className="mt-8">
      <div className="flex items-end justify-between px-5 mb-3">
        <div>
          {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
          <h2 className="font-display text-lg text-paper">{title}</h2>
        </div>
        {onSeeAll && (
          <button
            onClick={onSeeAll}
            className="flex items-center gap-0.5 text-xs font-semibold text-muted hover:text-brand-glow tap"
          >
            See all <ChevronRight size={14} />
          </button>
        )}
      </div>

      {hasChildren ? (
        <div className="rail flex gap-3 overflow-x-auto px-5 pb-1 snap-x snap-mandatory">
          {children}
        </div>
      ) : (
        <div className="mx-5 card px-4 py-6 text-center text-sm text-muted">
          {empty || "Nothing here yet."}
        </div>
      )}
    </section>
  );
}
