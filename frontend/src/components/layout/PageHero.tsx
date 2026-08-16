interface PageHeroProps {
  title: string
  subtitle: string
}

export function PageHero({ title, subtitle }: PageHeroProps) {
  return (
    <div className="mb-10 space-y-3 border-b border-border pb-8">
      <h1 className="font-display text-4xl tracking-tight md:text-5xl">{title}</h1>
      <p className="max-w-2xl text-base text-muted md:text-lg">{subtitle}</p>
    </div>
  )
}
