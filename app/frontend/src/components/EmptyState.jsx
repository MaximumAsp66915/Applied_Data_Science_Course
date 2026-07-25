export default function EmptyState({ icon: Icon, title, hint }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      {Icon && (
        <div className="w-14 h-14 rounded-full bg-surface border border-line/60 flex items-center justify-center mb-4">
          <Icon size={22} className="text-muted" />
        </div>
      )}
      <p className="font-display text-lg text-paper">{title}</p>
      {hint && <p className="text-sm text-muted mt-1 max-w-xs">{hint}</p>}
    </div>
  );
}
